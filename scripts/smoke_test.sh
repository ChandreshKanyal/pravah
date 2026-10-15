#!/usr/bin/env bash
# S17.4 smoke test: health -> demo AOI (cached) -> default run -> advisory (rules, instant) -> Gemini advisory job.
# Usage: scripts/smoke_test.sh [BASE]   (default: the Firebase Hosting URL; use http://localhost:8080 locally)
set -euo pipefail
BASE="${1:-https://project-0fd9c4ae-bf90-452f-a80.web.app}"
AOI=56f044f26351
j() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
step() { printf '\n== %s\n' "$1"; }

step "health"
curl -fsS "$BASE/api/health" | j 'd' ; curl -fsS "$BASE/api/health" | j 'd["ok"] and d["ee"] and d["vertex"] and d["firestore"]' | grep -q True

step "demo AOI (Rudraprayag, cached)"
curl -fsS -X POST "$BASE/api/aoi" -H 'content-type: application/json' \
  -d '{"bbox":[78.93,30.24,79.03,30.33],"name":"Rudraprayag 10km","mode":"river"}' | j 'd["aoi"]["aoi_id"], d["state"]'
curl -fsS "$BASE/api/aoi/$AOI/status" | j 'd["state"]' | grep -Eq "ready|partial"

step "default run (record rain, 4 h)"
T0=$(date +%s)
RUN=$(curl -fsS -X POST "$BASE/api/runs" -H 'content-type: application/json' \
  -d "{\"aoi_id\":\"$AOI\",\"rain_source\":\"historical_extreme\",\"duration_h\":4}" | j 'd["run_id"]')
echo "run $RUN in $(( $(date +%s) - T0 )) s"
curl -fsS "$BASE/api/runs/$RUN" | j 'd["rain_label"], d["people_to_evacuate"], d["capacity_gap_people"]'

step "advisory (rules fallback, instant)"
curl -fsS -X POST "$BASE/api/runs/$RUN/advisory?rules_only=true" | j 'd["generated_by"], len(d["recommendations"]), sorted({r["horizon"] for r in d["recommendations"]})'

step "advisory (Gemini, background job)"
curl -fsS -X POST "$BASE/api/runs/$RUN/advisory" | j 'd.get("status", "ready")'
for i in $(seq 1 45); do
  S=$(curl -fsS "$BASE/api/runs/$RUN/advisory" | j 'd.get("status","ready")')
  [ "$S" != "pending" ] && break; sleep 4
done
curl -fsS "$BASE/api/runs/$RUN/advisory" | j 'd.get("status"), d.get("generated_by"), len(d.get("recommendations", []))'
echo; echo "SMOKE TEST PASSED"
