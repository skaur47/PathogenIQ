#!/usr/bin/env bash
# PathogenIQ full pipeline runner.
# Usage:
#   ./run_pipeline.sh                               # uses production API
#   PATHOGENIQ_API=https://custom.fly.dev ./run_pipeline.sh
#
# Runs the full pipeline in order:
#   1. Ingest (CDC + WHO + ProMED + News)
#   2. Sentinel  →  3. Scholar  →  4. Dedup + Graph Sync
#   5. Research  →  6. Verify Research
#   7. Hypothesis  →  8. Verify Hypothesis
set -euo pipefail

API="${PATHOGENIQ_API:-https://pathogeniq-api.fly.dev}/api/v1"
POLL_INTERVAL=12   # seconds between status polls
MAX_POLLS=50       # ~10 minutes max per step before timeout

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ts()   { date '+%H:%M:%S'; }
log()  { echo -e "${CYAN}[$(ts)]${NC} $*"; }
ok()   { echo -e "${GREEN}[$(ts)] ✓${NC} $*"; }
warn() { echo -e "${YELLOW}[$(ts)] ⚠${NC} $*"; }
err()  { echo -e "${RED}[$(ts)] ✗${NC} $*" >&2; }
step() { echo -e "\n${BOLD}${BLUE}▶ $*${NC}"; }

# Extract a key from a JSON string using Python (no jq dependency)
json_field() {
  python3 -c "import sys,json; print(json.loads(sys.argv[1]).get(sys.argv[2],'')||'')" \
    "$1" "$2" 2>/dev/null || true
}

# POST to an API endpoint and return the job_id
trigger() {
  local endpoint="$1" label="$2" body="${3:-}"
  log "Triggering $label..."
  local resp
  if [[ -n "$body" ]]; then
    resp=$(curl -sf -X POST "${API}/${endpoint}" \
      -H "Content-Type: application/json" -d "$body") \
      || { err "Failed to trigger $label — is the API reachable at ${API}?"; exit 1; }
  else
    resp=$(curl -sf -X POST "${API}/${endpoint}" \
      -H "Content-Type: application/json") \
      || { err "Failed to trigger $label — is the API reachable at ${API}?"; exit 1; }
  fi
  local jid
  jid=$(json_field "$resp" "job_id")
  if [[ -z "$jid" ]]; then
    err "No job_id returned for $label"
    echo "$resp" >&2
    exit 1
  fi
  echo "$jid"
}

# Poll a job until complete or failed
poll_job() {
  local job_id="$1" label="$2" polls=0 status resp
  while (( polls < MAX_POLLS )); do
    resp=$(curl -sf "${API}/ingestion/jobs/${job_id}" 2>/dev/null) \
      || { warn "Poll request failed, retrying in ${POLL_INTERVAL}s..."; sleep $POLL_INTERVAL; polls=$(( polls + 1 )); continue; }
    status=$(json_field "$resp" "status")
    case "$status" in
      complete)
        ok "$label"
        return 0
        ;;
      failed)
        err "$label FAILED: $(json_field "$resp" "error")"
        return 1
        ;;
      not_found)
        warn "$label: job not found (may have expired or already ran)"
        return 1
        ;;
      queued|in_progress)
        log "$label: $status... (${polls}/${MAX_POLLS})"
        ;;
      *)
        log "$label: $status"
        ;;
    esac
    sleep $POLL_INTERVAL
    polls=$(( polls + 1 ))
  done
  err "$label timed out after $(( MAX_POLLS * POLL_INTERVAL ))s"
  return 1
}

# Trigger + poll in one call
run_step() {
  local endpoint="$1" label="$2" body="${3:-}"
  local jid
  jid=$(trigger "$endpoint" "$label" "$body")
  poll_job "$jid" "$label"
}

# ── Main ─────────────────────────────────────────────────────────────────────────
START=$(date +%s)
echo ""
echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${BLUE}  PathogenIQ Pipeline — $(date '+%Y-%m-%d %H:%M')${NC}"
echo -e "${BLUE}  API: ${API}${NC}"
echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ── 1. Ingest all sources ────────────────────────────────────────────────────────
step "1/9  Data ingestion (CDC + WHO + ProMED + News)"
CDC_JOB=$(trigger    "ingestion/trigger" "CDC"    '{"source":"cdc"}')
WHO_JOB=$(trigger    "ingestion/trigger" "WHO"    '{"source":"who"}')
PROMED_JOB=$(trigger "ingestion/trigger" "ProMED" '{"source":"promed"}')
NEWS_JOB=$(trigger   "ingestion/trigger" "News"   '{"source":"news"}')
# Jobs run in parallel on the server; polling sequentially is fine
poll_job "$CDC_JOB"    "CDC collection"
poll_job "$WHO_JOB"    "WHO collection"
poll_job "$PROMED_JOB" "ProMED collection"
poll_job "$NEWS_JOB"   "News collection"

# ── 2. Sentinel ──────────────────────────────────────────────────────────────────
step "2/9  Sentinel Agent (extract pathogen mentions)"
run_step "agents/trigger/sentinel" "Sentinel Agent"

# ── 3. Scholar ───────────────────────────────────────────────────────────────────
step "3/9  Scholar Agent (synthesize biological profiles)"
run_step "agents/trigger/scholar" "Scholar Agent"

# ── 4. Dedup + Graph Sync ────────────────────────────────────────────────────────
step "4/9  Deduplicator + Knowledge Graph sync"
run_step "agents/trigger/dedup"      "Deduplicator"
run_step "agents/trigger/graph-sync" "Graph Sync"

# ── 5. Research ──────────────────────────────────────────────────────────────────
step "5/9  Research Agent (PubMed literature mining per pathogen)"
run_step "agents/trigger/research" "Research Agent"

# ── 6. Verify Research ───────────────────────────────────────────────────────────
step "6/9  Verifier — research quality gate"
run_step "agents/trigger/verify-research" "Verifier (research)"

# ── 7. Hypothesis ────────────────────────────────────────────────────────────────
step "7/9  Hypothesis Agent (research strategy synthesis)"
run_step "agents/trigger/hypothesis" "Hypothesis Agent"

# ── 8. Verify Hypothesis ─────────────────────────────────────────────────────────
step "8/9  Verifier — hypothesis quality gate"
run_step "agents/trigger/verify-hypothesis" "Verifier (hypothesis)"

# ── 9. Email Digest ───────────────────────────────────────────────────────────────
step "9/9  Email Digest"
GUARD_FILE="${HOME}/.pathogeniq_last_digest"
TODAY=$(date +%Y-%m-%d)
if [[ -f "$GUARD_FILE" ]] && [[ "$(cat "$GUARD_FILE")" == "$TODAY" ]]; then
  warn "Digest already sent today ($TODAY) — skipping. Delete ~/.pathogeniq_last_digest to force a resend."
else
  run_step "agents/trigger/send-newsletter" "Email Digest"
  echo "$TODAY" > "$GUARD_FILE"
  ok "Digest guard saved to ${GUARD_FILE}"
fi

# ── Done ─────────────────────────────────────────────────────────────────────────
ELAPSED=$(( $(date +%s) - START ))
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${GREEN}  ✓ Pipeline complete in $(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s${NC}"
echo -e "${GREEN}  Dashboard: https://pathogen-iq.vercel.app${NC}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
