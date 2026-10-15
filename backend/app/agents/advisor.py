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
Do not invent numbers, places or ids. Every number in 'why' must appear in the facts you cite. Priority P1 = life-safety
within the scenario window. Use the words estimated, susceptibility, suggested; never say "will flood" or "safe"
(shelters are "reachable in this scenario"). Building classes are proxies ("likely ..."). Include 3-5 limitations.

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
                headline = draft.headline
                vals = F._fact_numbers([x for x in facts["key_numbers"]] + list(F.fact_index(facts).values()), facts)
                if any(not F._ok_number(n, vals) for n in F._numbers(headline)):
                    dropped.append({"action": "headline", "reason": "numbers not in facts; replaced"})
                    headline = _rules_headline(facts)
                return F.finalize(run["run_id"], facts, kept, headline, draft.limitations, "gemini", dropped,
                                  gemini.model_name("pro"))
        except Exception as e:  # any Gemini/parse failure -> deterministic brief
            log.warning("advisor fell back to rules: %s", e)
    headline = _rules_headline(facts)
    recs, _ = F.validate(rules, facts)  # attaches locations; rules cite only existing ids
    return F.finalize(run["run_id"], facts, recs or rules, headline, F.RULE_LIMITATIONS, "rules_fallback")


def _rules_headline(facts: dict) -> str:
    k = {x["id"]: x["value"] for x in facts["key_numbers"]}
    return (f"An estimated {k['K7']} people need to move in this scenario; capacity gap {k['K3']}, "
            f"{k['K4']} bridges closing, {k['K1']} people in flood water at the peak.")
