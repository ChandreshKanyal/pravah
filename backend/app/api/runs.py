import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
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
def create_run(params: ScenarioParams, flow: bool = True, user: dict = Depends(require("analyst"))):
    """`flow=false` (quick previews): no 2D flow model in the run (river and hollow water only, labelled), and none in
    the background; the 3D view starts it when opened."""
    try:
        result = run_pipeline(params, flow_model=flow)
    except AreaNotReady as e:
        raise HTTPException(409, str(e))
    if not flow:
        return result
    try:  # the 2D water-flow model runs in the background for the 3D view
        from app.pipeline import flow
        flow.start(result.run_id)
    except Exception:  # noqa: BLE001
        log.exception("flow model not started for %s", result.run_id)
    return result


RUN_JOB_LOST_S = 960  # past Cloud Run's 900 s request timeout plus margin: a job still "running" was lost with its instance
_run_pool = ThreadPoolExecutor(2)  # flow simulations queue on their own lock (pipeline/flow.py)


def _run_job(job_id: str, params: ScenarioParams, flow: bool, user: dict) -> None:
    try:
        result = create_run(params, flow, user)
        fs.merge_doc("run_jobs", job_id, {"status": "done", "run_id": result.run_id})
    except HTTPException as e:
        fs.merge_doc("run_jobs", job_id, {"status": "error", "code": e.status_code, "error": str(e.detail)[:500]})
    except Exception as e:  # noqa: BLE001
        log.exception("run job %s failed", job_id)
        fs.merge_doc("run_jobs", job_id, {"status": "error", "code": 500, "error": f"{e.__class__.__name__}: {e}"[:500]})


@router.post("/api/run-jobs")
def start_run_job(params: ScenarioParams, flow: bool = True, user: dict = Depends(require("analyst"))):
    """The website's way to run a scenario: answers at once with a job id, and the page polls GET /api/run-jobs/{id}.
    A run with the flow model takes minutes on Cloud Run, and a connection held silent that long can be dropped on the
    way (seen on a phone hotspot: the run finished, the reply never arrived). The job state lives in Firestore, so a
    poll answered by another instance still sees it. POST /api/runs stays for scripts and the smoke test."""
    job_id = uuid.uuid4().hex[:12]
    fs.set_doc("run_jobs", job_id, {"status": "running", "aoi_id": params.aoi_id,
                                    "started_at": datetime.now(timezone.utc).isoformat()})
    _run_pool.submit(_run_job, job_id, params, flow, user)
    return {"job_id": job_id, "status": "running"}


@router.get("/api/run-jobs/{job_id}")
def get_run_job(job_id: str):
    """{status: running | done | error, run_id when done, code and error when it failed}."""
    doc = fs.get_doc("run_jobs", job_id)
    if not doc:
        raise HTTPException(404, "Unknown run job")
    if doc.get("status") == "running":
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(doc["started_at"])).total_seconds()
        if age > RUN_JOB_LOST_S:
            return {**doc, "status": "error", "code": 504, "error": "The run stopped without a result (the server restarted). Please run it again."}
    return doc


@router.delete("/api/runs/{run_id}")
def delete_run(run_id: str, user: dict = Depends(require("analyst"))):
    """Permanently delete a run (files, brief, 3D model, alert, drills). Archive is the reversible option."""
    if not fs.get_doc("runs", run_id):
        raise HTTPException(404, "Unknown run")
    from app.pipeline import cleanup
    res = cleanup.delete_run(run_id)
    audit("delete_run", user, run_id=run_id, aoi_id=res.get("aoi_id"))
    return res


class RunMeta(BaseModel):
    title: str | None = None
    notes: str | None = None
    starred: bool | None = None
    archived: bool | None = None
    make_current: bool | None = None  # this run becomes the one the Brief, Map and 3D open by default


@router.patch("/api/runs/{run_id}/meta")
def run_meta(run_id: str, body: RunMeta, user: dict = Depends(require("analyst"))):
    """Name, annotate, star or archive a saved run (an experiment); results are never changed."""
    doc = fs.get_doc("runs", run_id)
    if not doc:
        raise HTTPException(404, "Unknown run")
    fields = {k: v for k, v in body.model_dump(exclude={"make_current"}).items() if v is not None}
    if "title" in fields:
        fields["title"] = fields["title"].strip()[:120] or None
    if "notes" in fields:
        fields["notes"] = fields["notes"][:4000]
    if fields:
        fs.merge_doc("runs", run_id, fields)
    if body.make_current:
        fs.update_aoi(doc["aoi_id"], {"latest_run_id": run_id})
    audit("run_meta", user, aoi_id=doc["aoi_id"], run_id=run_id, fields=sorted(fields) + (["make_current"] if body.make_current else []))
    return {"run_id": run_id, **fields}


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
        out["history"] = {"gfd_events": len(doc.get("gfd_events", [])),
                          "agreement_pct": doc.get("agreement_pct")}
    return out


_jobs: dict = {}
_jobs_lock = threading.Lock()
_pool = ThreadPoolExecutor(4)  # advisory drafts (Gemini, ~50 s each)


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
def advisory(run_id: str, refresh: bool = False, rules_only: bool = False, user: dict = Depends(require("analyst"))):
    """S15.5: return the cached advisory, or start generating it in the background and return {status: pending}.
    Gemini with high thinking takes ~50 s, beyond Firebase Hosting's 60 s rewrite budget, so the UI polls GET.
    A plain `def`: its Firestore calls block, and on the event loop they stalled every other request."""
    run = fs.get_doc("runs", run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    if rules_only:  # instant deterministic brief (also the forced-fallback test path)
        from app.agents.advisor import generate_advisory
        return generate_advisory(run, area_extra(run["aoi_id"], run_id), False).model_dump(mode="json")
    doc = fs.get_doc("advisories", run_id)
    if doc and doc.get("status", "ready") == "ready" and not refresh:
        return doc
    with _jobs_lock:
        if run_id in _jobs:
            return {"status": "pending", "run_id": run_id}
        _jobs[run_id] = None  # claimed: a second request meanwhile does not start another draft
    try:  # keep the current version readable while the new one is drafted (a new version never overwrites history)
        fs.set_doc("advisories", run_id, {**(doc or {}), "status": "pending"})
        _jobs[run_id] = _pool.submit(_generate_and_store, run_id, user)
    except Exception:
        _jobs.pop(run_id, None)
        raise
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
    from app.models.advisory import DEPARTMENTS_HI, KEY_LABELS_HI
    hi = lang == "hi"
    for k in cur.get("key_numbers", [])[:4]:
        v = k.get("rounded") if k.get("rounded") is not None else k["value"]
        rng = f" ({k['range'][0]:,}-{k['range'][1]:,})" if k.get("range") else ""
        label = KEY_LABELS_HI.get(k["evidence_id"], k["label"]) if hi else k["label"]
        L.append(f"- {label}: {v:,}{rng} {k['unit'] if k['unit'] != 'people' and not hi else ''}".rstrip())
    L += ["", "*Actions*" if lang == "en" else "*कार्रवाई*" if lang == "hi" else "*Actions*"]
    for r in [r for r in cur["recommendations"] if r["horizon"] == horizon][:8]:
        t = T.get(r["id"], {})
        owner = DEPARTMENTS_HI.get(r.get("owner", ""), r.get("owner", "")) if hi else r.get("owner", "")
        L.append(f"{r['priority']} {t.get('action') or r['action']} | {owner} | {t.get('act_by') or r.get('act_by', '')}")
    if cur.get("supplies"):
        sup_names = (tr or {}).get("supplies") or []
        L += ["", f"*{cur.get('supply_days', 3)} दिनों की राहत सामग्री*" if hi else f"*Supplies for {cur.get('supply_days', 3)} days*"]
        for i, s in enumerate(cur["supplies"][:4]):
            name = sup_names[i] if hi and i < len(sup_names) else s["item"]
            L.append(f"- {name}: {s['quantity']:,} {s['unit']} ({'अधिकतम' if hi else 'plan up to'} {s['quantity_high']:,})")
    L += ["", cur["disclaimer"]] + ([(tr or {}).get("disclaimer", "")] if hi and tr else [])
    return Response("\n".join(L), media_type="text/plain; charset=utf-8")


@router.get("/api/runs/{run_id}/alert")
def get_alert(run_id: str):
    """The latest public-alert draft (CAP 1.2 fields, English and Hindi) for a run, if one was drafted."""
    a = fs.get_doc("alerts", run_id)
    if not a:
        raise HTTPException(404, "No alert drafted yet")
    return a


@router.post("/api/runs/{run_id}/alert")
def draft_alert(run_id: str, user: dict = Depends(require("analyst"))):
    """Draft a public alert (agents/alerts.py): Gemini text checked against the facts, flooded-area polygons, CAP levels.
    A plain `def` (runs in the threadpool): loading an area takes seconds and must not hold up the event loop."""
    from app.agents import alerts
    from app.pipeline.run_pipeline import load_area
    run = fs.get_doc("runs", run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    aoi = fs.get_aoi(run["aoi_id"]) or {}
    a = alerts.draft(run, load_area(run["aoi_id"]), aoi.get("name") or "the area")
    fs.set_doc("alerts", run_id, a)
    audit("alert_draft", user, run_id, by_model=a["by"])
    return a


@router.get("/api/runs/{run_id}/alert/cap.xml")
def alert_cap(run_id: str):
    """CAP 1.2 XML (status Draft) for import into SACHET or any CAP-compliant system after review."""
    from app.agents import alerts
    a = fs.get_doc("alerts", run_id)
    if not a:
        raise HTTPException(404, "No alert drafted yet")
    run = fs.get_doc("runs", run_id) or {}
    name = (fs.get_aoi(run.get("aoi_id", "")) or {}).get("name") or "the area"
    return Response(alerts.cap_xml(a, name), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="pravah-alert-{run_id}.cap.xml"'})
