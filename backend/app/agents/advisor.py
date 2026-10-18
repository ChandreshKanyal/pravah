"""S15.2 advisor: Gemini (PRO tier) drafts the brief from the facts JSON only; the validator and the rules fallback
make sure every recommendation is grounded in ids and numbers that exist."""
import json
import logging

from app.models.advisory import Advisory, AdvisoryDraft, Recommendation
from app.pipeline import facts as F
from app.services import gemini

log = logging.getLogger(__name__)

PROMPT = """You are drafting a decision-support brief for district disaster-management officials. Use ONLY the facts JSON.
Produce 6-12 recommendations across three horizons:
- immediate (incoming storm: who moves first, routes, shelters to open, bridges to close, where to stage ambulances/police/medical teams),
- seasonal (pre-monsoon: drains to clear, roads/slopes to inspect, shelters to stock),
- structural (long-term: where permanent shelters/medical facilities or better evacuation roads are justified).
Each recommendation must list evidence_ids that exist in the facts and a 'why' that quotes numbers from those facts.
Write for a District Magistrate: name places (the place/name fields: villages, wards, roads, shelters) in action and
location_label; never use a bare id like "C1" there (ids go only in evidence_ids). Pick the one responsible department
(owner) per action. Prefer rounded people figures ("rounded") when you quote key numbers.
Do not invent numbers, places or ids. Every number in 'why' must appear in the facts you cite. Priority P1 = life-safety
within the scenario window. The headline is a 2-sentence situation summary (what is coming, where the risk is).
Use the words estimated, susceptibility, suggested; never say "will flood" or "safe"
(shelters are "reachable in this scenario"). Building classes are proxies ("likely ..."). Only recommend hazards present in the
facts (flood, water-logging); this is not a landslide, cyclone or earthquake tool. A bridge with reason "overtopped"
closes when the river reaches its deck; one with reason construction, closed or disused is marked so in OpenStreetMap,
not closed by the storm: suggest confirming its status with PWD, not closing it. Include 3-5 limitations.
"fixes" (when present) is the area's ranked list of pre-monsoon works: turn the most important 2-4 into seasonal (or,
for a second road out, structural) recommendations citing their FX ids, with the fix's place and department. A fix with
basis "web" is a waterlogging spot reported online: say "reported"; one with basis "model" or confidence "check" is
suggested for inspection, not confirmed.

FACTS JSON:
{facts}
"""


def generate_advisory(run: dict, area_extra: dict | None = None, use_gemini: bool = True) -> Advisory:
    facts = F.build_facts(run, area_extra)
    rules = F.rules_advisory(facts)
    if use_gemini:
        try:
            draft: AdvisoryDraft = gemini.generate_json(PROMPT.format(facts=json.dumps(facts, separators=(",", ":"))),
                                                        AdvisoryDraft, tier="pro", temperature=0.2)
            recs = [Recommendation(**r.model_dump()) for r in draft.recommendations]
            kept, dropped = F.validate(recs, facts)
            for h in ("immediate", "seasonal", "structural"):  # S15.3 step 3: fill empty horizons from the rules
                if not any(r.horizon == h for r in kept):
                    kept += [r for r in rules if r.horizon == h][:2]
            if kept:
                summary = draft.headline
                vals = F._fact_numbers([x for x in facts["key_numbers"]] + list(F.fact_index(facts).values()), facts)
                if any(not F._ok_number(n, vals) for n in F._numbers(summary)):
                    dropped.append({"action": "summary", "reason": "numbers not in facts; removed"})
                    summary = ""
                return F.finalize(run["run_id"], facts, kept, F.bottom_line(facts), draft.limitations, "gemini", dropped,
                                  gemini.model_name("pro"), summary=summary)
        except Exception as e:  # any Gemini/parse failure -> deterministic brief
            log.warning("advisor fell back to rules: %s", e)
    recs, _ = F.validate(rules, facts)  # attaches locations; rules cite only existing ids
    return F.finalize(run["run_id"], facts, recs or rules, F.bottom_line(facts), F.RULE_LIMITATIONS, "rules_fallback")
