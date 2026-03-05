#!/usr/bin/env bash
# build_and_push.sh – Build arm64 Docker image and push to ECR
#
# Usage:
#   ./scripts/build_and_push.sh \
#     --repo  123456789012.dkr.ecr.us-east-1.amazonaws.com/cw-sre-agent \
#     --tag   latest \
#     --region us-east-1
#
# Environment variable alternative (all three are optional if already exported):
#   ECR_REPO, IMAGE_TAG, AWS_REGION
#
# Prerequisites:
#   • Docker with buildx enabled (comes with Docker Desktop)
#   • AWS CLI v2 with credentials configured
#   • Appropriate ECR push permissions

set -euo pipefail

########################################
# Defaults
########################################
ECR_REPO="${ECR_REPO:-}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
AWS_REGION="${AWS_REGION:-us-east-1}"
PLATFORM="linux/arm64"

########################################
# Parse flags
########################################
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)    ECR_REPO="$2";   shift 2 ;;
    --tag)     IMAGE_TAG="$2";  shift 2 ;;
    --region)  AWS_REGION="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

########################################
# Validate
########################################
if [[ -z "$ECR_REPO" ]]; then
  echo "❌  --repo is required (or set ECR_REPO env var)" >&2
  echo "    Example: 123456789012.dkr.ecr.us-east-1.amazonaws.com/cw-sre-agent" >&2
  exit 1
fi

FULL_IMAGE="${ECR_REPO}:${IMAGE_TAG}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "➜  Platform : ${PLATFORM}"
echo "➜  Image    : ${FULL_IMAGE}"
echo "➜  Region   : ${AWS_REGION}"
echo ""

########################################
# ECR login
########################################
echo "🔐  Logging in to ECR…"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin \
      "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

########################################
# Build + push
########################################
echo "🔨  Building ${PLATFORM} image…"
docker buildx build \
  --platform "${PLATFORM}" \
  --tag      "${FULL_IMAGE}" \
  --push \
  "${APP_DIR}"

echo ""
echo "✅  Successfully pushed: ${FULL_IMAGE}"
echo ""
echo "Next step — update Terraform variable or env var:"
echo "  export TF_VAR_image_tag=${IMAGE_TAG}"
