#!/usr/bin/env bash
#######################################################################
# run_demo.sh – End-to-end demo: inject logs → invoke agent → verify
#
# Usage:
#   ./scripts/run_demo.sh [--region us-west-2]
#
# Prerequisites:
#   - Terraform infrastructure already applied (terraform apply)
#   - AWS credentials with access to the deployed resources
#   - Python 3.12+ with boto3 installed
#######################################################################

set -euo pipefail

REGION="${1:-us-west-2}"
LOG_GROUP="/demo/app-logs"
SSM_PARAM="/sre-agent/actions/latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "═══════════════════════════════════════════════════════════════"
echo "  SRE Agent Demo – CloudWatch Error Detection & Remediation"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Region:     $REGION"
echo "  Log Group:  $LOG_GROUP"
echo "  SSM Param:  $SSM_PARAM"
echo ""

# ── Step 1: Inject demo logs ──────────────────────────────────────

echo "▸ Step 1: Injecting demo logs..."
python3 "$SCRIPT_DIR/inject_demo_logs.py" \
  --log-group "$LOG_GROUP" \
  --region "$REGION" \
  --count 150 \
  --error-ratio 0.20 \
  --hours-back 6
echo ""

# ── Step 2: Check SSM parameter before ────────────────────────────

echo "▸ Step 2: Current SSM parameter value (before agent):"
aws ssm get-parameter \
  --name "$SSM_PARAM" \
  --region "$REGION" \
  --query 'Parameter.Value' \
  --output text 2>/dev/null | python3 -m json.tool || echo "  (parameter not found – will be created)"
echo ""

# ── Step 3: Wait for log watcher Lambda to trigger ────────────────

echo "▸ Step 3: Waiting for CloudWatch subscription filter to trigger log-watcher Lambda..."
echo "  (Lambda invokes AgentCore → agent analyzes logs → writes to SSM)"
echo ""

# Poll for SSM parameter update (up to 60 seconds with 10s intervals)
WAIT_TIME=0
MAX_WAIT=60
POLL_INTERVAL=10

INITIAL_VALUE=$(aws ssm get-parameter \
  --name "$SSM_PARAM" \
  --region "$REGION" \
  --query 'Parameter.Value' \
  --output text 2>/dev/null || echo "{\"status\": \"no_issues_detected\"}")

echo "  Initial SSM value: $INITIAL_VALUE"
echo ""

while [ $WAIT_TIME -lt $MAX_WAIT ]; do
  sleep $POLL_INTERVAL
  WAIT_TIME=$((WAIT_TIME + POLL_INTERVAL))

  CURRENT_VALUE=$(aws ssm get-parameter \
    --name "$SSM_PARAM" \
    --region "$REGION" \
    --query 'Parameter.Value' \
    --output text 2>/dev/null || echo "")

  if [ -n "$CURRENT_VALUE" ] && [ "$CURRENT_VALUE" != "$INITIAL_VALUE" ]; then
    echo "  ✓ SSM parameter updated after $WAIT_TIME seconds"
    break
  fi

  echo "  Waiting... ($WAIT_TIME/$MAX_WAIT seconds)"
done

echo ""

# ── Step 4: Display final SSM parameter ─────────────────────────────

echo "▸ Step 4: Final SSM parameter value (agent remediation action):"
aws ssm get-parameter \
  --name "$SSM_PARAM" \
  --region "$REGION" \
  --query 'Parameter.Value' \
  --output text 2>/dev/null | python3 -m json.tool || echo "  (parameter not updated)"
echo ""

echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ Demo complete!"
echo "═══════════════════════════════════════════════════════════════"
