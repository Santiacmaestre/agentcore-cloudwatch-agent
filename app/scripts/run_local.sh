#!/usr/bin/env bash
# run_local.sh – Run the SRE agent CLI locally with required env vars
#
# Usage:
#   ./scripts/run_local.sh
#
# Set variables either in a .env file (auto-loaded) or as environment exports.
# Required env vars:
#   AWS_REGION       – e.g. us-east-1
#   MODEL_ID         – e.g. amazon.nova-premier-v1:0
#   MEMORY_ID        – AgentCore memory resource ID
#   MEMORY_ACTOR_ID  – Actor namespace
#
# Optional:
#   MAX_RESULT_CHARS – default 20000
#   DEBUG_MODE       – true/false

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Load .env if it exists ──────────────────────────────────────────────────
ENV_FILE="${APP_DIR}/.env"
if [[ -f "${ENV_FILE}" ]]; then
  echo "📄  Loading environment from ${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a; source "${ENV_FILE}"; set +a
fi

# ── Validate required vars ──────────────────────────────────────────────────
REQUIRED=(AWS_REGION MODEL_ID MEMORY_ID MEMORY_ACTOR_ID)
MISSING=()
for var in "${REQUIRED[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    MISSING+=("$var")
  fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "❌  Missing required env vars:" >&2
  for v in "${MISSING[@]}"; do echo "    $v" >&2; done
  echo ""
  echo "  Options:" >&2
  echo "    1) Create ${APP_DIR}/.env and add KEY=VALUE pairs" >&2
  echo "    2) Export: export AWS_REGION=us-east-1  etc." >&2
  exit 1
fi

# ── Launch the CLI ──────────────────────────────────────────────────────────
echo "🚀  Starting CW SRE Agent…"
echo "    Region : ${AWS_REGION}"
echo "    Model  : ${MODEL_ID}"
echo ""

cd "${APP_DIR}"
exec python -m cw_sre_agent "$@"
