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

# ── Step 3: Wait for log watcher Lambda to filter events ────────────

echo "▸ Step 3: Waiting for CloudWatch subscription filter to trigger log-watcher Lambda..."
echo "  (Lambda filters ERROR/CRITICAL events and writes to SSM /sre-agent/error-detected)"
echo ""

# Poll for error detection (up to 30 seconds with 5s intervals)
WAIT_TIME=0
MAX_WAIT=30
POLL_INTERVAL=5

ERROR_SUMMARY=""

while [ $WAIT_TIME -lt $MAX_WAIT ]; do
  ERROR_SUMMARY=$(aws ssm get-parameter \
    --name "/sre-agent/error-detected" \
    --region "$REGION" \
    --query 'Parameter.Value' \
    --output text 2>/dev/null || echo "")

  if [ -n "$ERROR_SUMMARY" ]; then
    echo "  ✓ Errors detected by log-watcher Lambda!"
    echo ""
    echo "  Error summary:"
    echo "$ERROR_SUMMARY" | python3 -m json.tool 2>/dev/null || echo "$ERROR_SUMMARY"
    echo ""
    break
  fi

  WAIT_TIME=$((WAIT_TIME + POLL_INTERVAL))
  echo "  Waiting for Lambda trigger... ($WAIT_TIME/$MAX_WAIT seconds)"
  sleep $POLL_INTERVAL
done

if [ -z "$ERROR_SUMMARY" ]; then
  echo "  ⚠ No errors detected by Lambda (may take a few moments)"
fi

echo ""

# ── Step 4: Wait for agent remediation ────────────────────────────

echo "▸ Step 4: Waiting for agent to analyse logs and write remediation..."
echo "  (Lambda invokes AgentCore runtime endpoint → agent writes to $SSM_PARAM)"
echo ""

# Capture the current value so we can detect when it changes
BEFORE_VALUE=$(aws ssm get-parameter \
  --name "$SSM_PARAM" \
  --region "$REGION" \
  --query 'Parameter.LastModifiedDate' \
  --output text 2>/dev/null || echo "")

WAIT_TIME=0
MAX_WAIT=300
POLL_INTERVAL=10
REMEDIATION=""

while [ $WAIT_TIME -lt $MAX_WAIT ]; do
  CURRENT_VALUE=$(aws ssm get-parameter \
    --name "$SSM_PARAM" \
    --region "$REGION" \
    --query 'Parameter.LastModifiedDate' \
    --output text 2>/dev/null || echo "")

  if [ -n "$CURRENT_VALUE" ] && [ "$CURRENT_VALUE" != "$BEFORE_VALUE" ]; then
    REMEDIATION=$(aws ssm get-parameter \
      --name "$SSM_PARAM" \
      --region "$REGION" \
      --query 'Parameter.Value' \
      --output text 2>/dev/null || echo "")
    echo "  ✓ Agent wrote remediation action!"
    echo ""
    echo "  Remediation:"
    echo "$REMEDIATION" | python3 -m json.tool 2>/dev/null || echo "$REMEDIATION"
    echo ""
    break
  fi

  WAIT_TIME=$((WAIT_TIME + POLL_INTERVAL))
  echo "  Waiting for agent response... ($WAIT_TIME/$MAX_WAIT seconds)"
  sleep $POLL_INTERVAL
done

if [ -z "$REMEDIATION" ]; then
  echo "  ⚠ Agent did not write remediation within ${MAX_WAIT}s"
  echo "  Check Lambda logs for errors:"
  echo "    aws logs tail /aws/lambda/cwlogs_diagnoser-log-watcher --region $REGION --since 10m"
fi

echo ""

echo "═══════════════════════════════════════════════════════════════"
if [ -n "$REMEDIATION" ]; then
  echo "  ✅ End-to-end demo complete!"
  echo "  Logs → Lambda → Agent → Remediation"
else
  echo "  ⏳ Demo partially complete."
  echo "  ➜ Check Lambda / agent logs for status"
fi
echo "═══════════════════════════════════════════════════════════════"
