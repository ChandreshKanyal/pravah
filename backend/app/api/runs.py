import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.auth import current_user, require

from app.models.run import RunResult
from app.models.scenario import ScenarioParams
from app.pipeline.run_pipeline import AreaNotReady, run_pipeline
from app.services import firestore as fs
from app.services import storage

router = APIRouter()
log = logging.getLogger(__name__)


@router.post("/api/runs", response_model=RunResult)
def create_run(params: ScenarioParams, user: dict = Depends(require("analyst"))):
    try:
        return run_pipeline(params)
    except AreaNotReady as e:
        raise HTTPException(409, str(e))


@router.get("/api/runs/{run_id}", response_model=RunResult)
def get_run(run_id: str):
    doc = fs.get_doc("runs", run_id)
    if not doc:
        raise HTTPException(404, "Unknown run")
    return doc


def area_extra(aoi_id: str, run_id: str) -> dict:
    """Area-level facts for the advisory: medical, crowding, verification queue, forecast, history (best effort)."""
    out: dict = {}
    for key, name in (("medical", "medical.json"), ("crowding", "crowd_hotspots.json")):
        if storage.exists(aoi_id, name):
            out[key] = storage.get_json(aoi_id, name)
    try:
        import json
        out["verification"] = json.loads(storage.get_run(run_id, "verification.json"))
    except Exception:
        pass
    try:
        from app.pipeline.run_pipeline import area_centroid, load_area
        from app.services.weather import get_provider
        lon, lat = area_centroid(load_area(aoi_id))
        daily = get_provider().daily(lat, lon, 10)
        if daily:
            w = max(daily, key=lambda d: d["precip_mm"])
            out["forecast"] = {"worst_day": w["date"], "max_daily_mm": round(w["precip_mm"], 1),
                               "source": "Google Maps Platform Weather API"}
    except Exception as e:
        log.info("advisory forecast unavailable: %s", e)
    try:
        from app.services import places
        out["places"] = places.area_places(aoi_id)
    except Exception:
        pass
    aoi = fs.get_aoi(aoi_id) or {}
    if aoi.get("official"):
        out["official"] = aoi["official"]
    doc = fs.get_doc("history_cache", aoi_id)
    if doc:
        out["history"] = {"gfd_events": len(doc.get("gfd_events", [])), "landslides": len(doc.get("landslides", [])),
                          "agreement_pct": doc.get("agreement_pct")}
    return out


_jobs: dict = {}
_pool = None


def audit(action: str, user: dict, run_id: str = "", **extra) -> None:
    """Append-only audit trail (who did what to which brief, when)."""
    try:
        fs.get_db().collection("audit").add({"at": datetime.now(timezone.utc).isoformat(), "action": action, "run_id": run_id,
                                             "by": user.get("name") or user.get("email") or "anonymous",
                                             "email": user.get("email", ""), "verified": bool(user.get("verified")), **extra})
    except Exception as e:
        log.warning("audit write failed: %s", e)


def _generate_and_store(run_id: str, user: dict | None = None) -> None:
    from app.agents.advisor import generate_advisory
    try:
        run = fs.get_doc("runs", run_id)
        prev = fs.get_doc("advisories", run_id) or {}
        version = int(prev.get("last_version") or prev.get("version") or 0) + 1
        adv = generate_advisory(run, area_extra(run["aoi_id"], run_id))
        doc = {**adv.model_dump(mode="json"), "status": "ready", "version": version, "last_version": version,
               "created_at": datetime.now(timezone.utc).isoformat(),
               "review": {"state": "draft", "by": "", "at": "", "note": ""}}
        if prev.get("approved_version"):  # the approved version stays on record; the new one starts as a draft
            doc["approved_version"] = prev["approved_version"]
        fs.set_doc("advisory_versions", f"{run_id}_v{version}", doc)  # immutable copy
        fs.set_doc("advisories", run_id, doc)
        fs.get_db().collection("runs").document(run_id).update({"advisory_id": run_id})
        audit("generate", user or {}, run_id, version=version, generated_by=adv.generated_by)
    except Exception as e:
        log.exception("advisory job failed")
        prev = fs.get_doc("advisories", run_id) or {}
        fs.set_doc("advisories", run_id, {**prev, "status": "error", "error": str(e)[:300]} if prev.get("headline") else
                   {"status": "error", "error": str(e)[:300]})
    finally:
        _jobs.pop(run_id, None)


@router.post("/api/runs/{run_id}/advisory")
async def advisory(run_id: str, refresh: bool = False, rules_only: bool = False, user: dict = Depends(require("analyst"))):
    """S15.5: return the cached advisory, or start generating it in the background and return {status: pending}.
    Gemini with high thinking takes ~50 s, beyond Firebase Hosting's 60 s rewrite budget, so the UI polls GET."""
    global _pool
    run = fs.get_doc("runs", run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    if rules_only:  # instant deterministic brief (also the forced-fallback test path)
        from app.agents.advisor import generate_advisory
        extra = await run_in_threadpool(area_extra, run["aoi_id"], run_id)
        return (await run_in_threadpool(generate_advisory, run, extra, False)).model_dump(mode="json")
    doc = fs.get_doc("advisories", run_id)
    if doc and doc.get("status", "ready") == "ready" and not refresh:
        return doc
    if run_id not in _jobs:
        from concurrent.futures import ThreadPoolExecutor
        _pool = _pool or ThreadPoolExecutor(4)
        # keep the current version readable while the new one is drafted (a new version never overwrites history)
        fs.set_doc("advisories", run_id, {**(doc or {}), "status": "pending"})
        _jobs[run_id] = _pool.submit(_generate_and_store, run_id, user)
    return {"status": "pending", "run_id": run_id}


@router.get("/api/runs/{run_id}/advisory")
def get_advisory(run_id: str):
    doc = fs.get_doc("advisories", run_id)
    if not doc:
        raise HTTPException(404, "No advisory yet")
    return doc


@router.get("/api/runs/{run_id}/advisory/versions")
def advisory_versions(run_id: str):
    """Every generated version (immutable), newest first, with its review state."""
    cur = fs.get_doc("advisories", run_id) or {}
    out = []
    for v in range(int(cur.get("last_version") or cur.get("version") or 0), 0, -1):
        d = fs.get_doc("advisory_versions", f"{run_id}_v{v}")
        if d:
            out.append({"version": v, "created_at": d.get("created_at"), "generated_by": d.get("generated_by"),
                        "review": d.get("review", {}), "headline": d.get("headline")})
    return out


@router.get("/api/runs/{run_id}/advisory/versions/{version}")
def advisory_version(run_id: str, version: int):
    d = fs.get_doc("advisory_versions", f"{run_id}_v{version}")
    if not d:
        raise HTTPException(404, "No such version")
    return d


class Review(BaseModel):
    state: str  # draft | reviewed | approved
    name: str = ""  # typed name when sign-in is off
    designation: str = ""  # e.g. "District Magistrate, Rudraprayag"
    note: str = ""
    version: int | None = None


@router.post("/api/runs/{run_id}/advisory/review")
def review_advisory(run_id: str, body: Review, user: dict = Depends(current_user)):
    """Draft -> reviewed -> approved, recorded on the immutable version and in the audit trail. Approving needs the
    approver role when sign-in is on; with sign-in off a typed name is required and recorded as unverified."""
    from app.auth import ROLES
    from app.config import get_settings
    if body.state not in ("draft", "reviewed", "approved"):
        raise HTTPException(422, "state must be draft, reviewed or approved")
    cfg = get_settings()
    if cfg.auth_required and not user["verified"]:
        raise HTTPException(401, "Sign in to review or approve")
    if body.state == "approved" and user["verified"] and ROLES.index(user["role"]) < ROLES.index("approver"):
        raise HTTPException(403, "Approving needs the approver role")
    name = user["name"] if user["verified"] else body.name.strip()
    if not name:
        raise HTTPException(422, "Enter your name to record the review")
    cur = fs.get_doc("advisories", run_id)
    if not cur or not cur.get("headline"):
        raise HTTPException(404, "No brief yet")
    version = body.version or int(cur.get("version") or 1)
    rev = {"state": body.state, "by": name, "designation": body.designation.strip(), "email": user.get("email", ""),
           "verified": bool(user["verified"]), "at": datetime.now(timezone.utc).isoformat(), "note": body.note.strip()[:500]}
    key = f"{run_id}_v{version}"
    vd = fs.get_doc("advisory_versions", key)
    if not vd:  # briefs generated before versioning: freeze the current one as v1
        vd = {**cur, "version": version}
    if (vd.get("review") or {}).get("state") == "approved" and body.state != "approved":
        raise HTTPException(409, "An approved version cannot be changed; generate a new version instead")
    vd["review"] = rev
    fs.set_doc("advisory_versions", key, vd)
    patch = {"review": rev} if int(cur.get("version") or 1) == version else {}
    if body.state == "approved":
        patch["approved_version"] = version
    if patch:
        fs.get_db().collection("advisories").document(run_id).update(patch)
    audit(f"review:{body.state}", {**user, "name": name}, run_id, version=version, note=rev["note"],
          designation=rev["designation"])
    return {**cur, **patch}


@router.get("/api/runs/{run_id}/audit")
def run_audit(run_id: str):
    rows = [d.to_dict() for d in fs.get_db().collection("audit").where("run_id", "==", run_id).limit(100).stream()]
    return sorted(rows, key=lambda r: r.get("at", ""), reverse=True)


_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")


@router.post("/api/runs/{run_id}/advisory/translate")
def translate_advisory(run_id: str, lang: str = "hi", user: dict = Depends(require("analyst"))):
    """Hindi (or another Indian language) version of the current brief by Gemini (fast tier). Numbers must survive
    unchanged (Western digits); any item whose numbers change keeps its English text. Cached per version."""
    from app.services import gemini
    names = {"hi": "Hindi", "mr": "Marathi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "gu": "Gujarati", "kn": "Kannada"}
    if lang not in names:
        raise HTTPException(422, "Unsupported language")
    cur = fs.get_doc("advisories", run_id)
    if not cur or not cur.get("headline"):
        raise HTTPException(404, "No brief yet")
    tr = (cur.get("translations") or {}).get(lang)
    if tr and tr.get("version") == cur.get("version"):
        return tr

    class TRec(BaseModel):
        id: str
        action: str
        location_label: str
        why: str
        act_by: str

    class TBrief(BaseModel):
        headline: str
        summary: str
        recommendations: list[TRec]
        limitations: list[str]
        supplies: list[str]
        disclaimer: str

    src = {"headline": cur["headline"], "summary": cur.get("summary", ""), "disclaimer": cur["disclaimer"],
           "recommendations": [{k: r.get(k, "") for k in ("id", "action", "location_label", "why", "act_by")} for r in cur["recommendations"]],
           "limitations": cur.get("limitations", []), "supplies": [x["item"] for x in cur.get("supplies", [])]}
    import json
    prompt = (f"Translate this disaster-management brief into {names[lang]} for district officials. Keep every number "
              "exactly as written in Western digits (0-9), keep ids like R1 unchanged, keep place names recognisable "
              "(use the common local spelling). Formal, plain administrative language.\n\n" + json.dumps(src, ensure_ascii=False))
    out: TBrief = gemini.generate_json(prompt, TBrief, tier="fast", temperature=0.1)

    def same(a: str, b: str) -> bool:
        return sorted(_DIGITS.findall(a or "")) == sorted(_DIGITS.findall(b or ""))
    recs, kept_en = {}, []
    for t in out.recommendations:
        en = next((r for r in src["recommendations"] if r["id"] == t.id), None)
        if en and same(en["why"], t.why) and same(en["action"], t.action) and same(en["act_by"], t.act_by):
            recs[t.id] = t.model_dump()
        elif en:
            kept_en.append(t.id)
    res = {"lang": lang, "version": cur.get("version"), "recommendations": recs, "kept_english": kept_en,
           "headline": out.headline if same(src["headline"], out.headline) else src["headline"],
           "summary": out.summary if same(src["summary"], out.summary) else src["summary"],
           "limitations": out.limitations if len(out.limitations) == len(src["limitations"]) else src["limitations"],
           "supplies": out.supplies if len(out.supplies) == len(src["supplies"]) else src["supplies"],
           "disclaimer": out.disclaimer, "model": gemini.model_name("fast")}
    fs.get_db().collection("advisories").document(run_id).update({f"translations.{lang}": res})
    audit("translate", user, run_id, lang=lang, version=cur.get("version"))
    return res


@router.get("/api/runs/{run_id}/advisory/share.txt")
def share_text(run_id: str, lang: str = "en", horizon: str = "immediate"):
    """Plain-text brief for WhatsApp/SMS and 2G connections: bottom line, key figures, actions with owner and deadline,
    supplies, review state and the exact disclaimer."""
    cur = fs.get_doc("advisories", run_id)
    if not cur or not cur.get("headline"):
        raise HTTPException(404, "No brief yet")
    run = fs.get_doc("runs", run_id) or {}
    aoi = fs.get_aoi(run.get("aoi_id", "")) or {}
    tr = (cur.get("translations") or {}).get(lang) if lang != "en" else None
    T = (tr or {}).get("recommendations", {})
    rv = cur.get("review") or {}
    state = {"approved": f"APPROVED by {rv.get('by')}{', ' + rv['designation'] if rv.get('designation') else ''}",
             "reviewed": f"Reviewed by {rv.get('by')}"}.get(rv.get("state"), "DRAFT, not yet approved")
    L = [f"*Pravah brief: {aoi.get('name', '')}* ({state}, v{cur.get('version', 1)})", "",
         (tr or {}).get("headline") or cur["headline"], ""]
    for k in cur.get("key_numbers", [])[:4]:
        v = k.get("rounded") if k.get("rounded") is not None else k["value"]
        rng = f" ({k['range'][0]:,}-{k['range'][1]:,})" if k.get("range") else ""
        L.append(f"- {k['label']}: {v:,}{rng} {k['unit'] if k['unit'] != 'people' else ''}".rstrip())
    L += ["", "*Actions*" if lang == "en" else "*कार्रवाई*" if lang == "hi" else "*Actions*"]
    for r in [r for r in cur["recommendations"] if r["horizon"] == horizon][:8]:
        t = T.get(r["id"], {})
        L.append(f"{r['priority']} {t.get('action') or r['action']} | {r.get('owner', '')} | {t.get('act_by') or r.get('act_by', '')}")
    if cur.get("supplies"):
        L += ["", f"*Supplies for {cur.get('supply_days', 3)} days*"]
        for s in cur["supplies"][:4]:
            L.append(f"- {s['item']}: {s['quantity']:,} {s['unit']} (plan up to {s['quantity_high']:,})")
    L += ["", cur["disclaimer"]]
    return Response("\n".join(L), media_type="text/plain; charset=utf-8")
