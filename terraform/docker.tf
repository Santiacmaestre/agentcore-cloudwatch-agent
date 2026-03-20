#######################################################################
# File: docker.tf
#
# Description:
#   Builds the agent Docker image for linux/arm64 and pushes it to ECR
#   whenever the Dockerfile, requirements, application code, or image
#   tag changes. Triggers are content-addressable to avoid unnecessary
#   rebuilds.
#
# Notes:
#   - linux/arm64 is required; AgentCore only supports arm64 runtimes.
#   - buildx create is idempotent; errors are suppressed intentionally.
#######################################################################

# Builds and pushes the arm64 agent image to ECR on any source change
resource "null_resource" "docker_build_push" {
  triggers = {
    dockerfile_sha    = filesha256("${path.module}/../app/Dockerfile")
    pyproject_sha     = filesha256("${path.module}/../app/pyproject.toml")
    agent_sha         = filesha256("${path.module}/../app/src/cw_sre_agent/agent.py")
    server_sha        = filesha256("${path.module}/../app/src/cw_sre_agent/server.py")
    cli_sha           = filesha256("${path.module}/../app/src/cw_sre_agent/cli.py")
    config_sha        = filesha256("${path.module}/../app/src/cw_sre_agent/config.py")
    memory_sha        = filesha256("${path.module}/../app/src/cw_sre_agent/memory.py")
    export_sha        = filesha256("${path.module}/../app/src/cw_sre_agent/export.py")
    logging_sha       = filesha256("${path.module}/../app/src/cw_sre_agent/logging.py")
    assume_role_sha   = filesha256("${path.module}/../app/src/cw_sre_agent/aws/assume_role.py")
    session_cache_sha = filesha256("${path.module}/../app/src/cw_sre_agent/aws/session_cache.py")
    remediation_sha   = filesha256("${path.module}/../app/src/cw_sre_agent/remediation.py")
    image_tag         = var.image_tag
    repo_url          = local.ecr_registry
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-lc"]
    command     = <<EOF
set -euo pipefail

echo "[INFO] Logging into ECR..."
aws ecr get-login-password --region ${var.region} \
  | docker login --username AWS --password-stdin ${local.ecr_registry}

echo "[INFO] Ensuring buildx builder exists..."
docker buildx create --use >/dev/null 2>&1 || true

echo "[INFO] Building & pushing (linux/arm64) -> ${local.image_uri}"
docker buildx build --platform linux/arm64 \
  -t ${local.image_uri} \
  --push \
  ${path.module}/../app

echo "[INFO] Done."
EOF
  }

  depends_on = [aws_ecr_repository.agent]
}