# Terraform — Infrastructure

Provisions all AWS resources required to run the CW SRE Agent on Amazon Bedrock AgentCore.

> **Back to root:** [../README.md](../README.md) | **Application:** [../app/README.md](../app/README.md)


## Table of Contents

1. [Resources Provisioned](#resources-provisioned)
2. [File Layout](#file-layout)
3. [Prerequisites](#prerequisites)
4. [Usage](#usage)
5. [Variables](#variables)
6. [Outputs](#outputs)
7. [Notes](#notes)


## Resources Provisioned

| Resource                               | File            | Description                                                                           |
|----------------------------------------|-----------------|---------------------------------------------------------------------------------------|
| `aws_bedrockagentcore_agent_runtime`   | `agentcore.tf`  | AgentCore runtime running the container                                               |
| `aws_bedrockagentcore_memory`          | `memory.tf`     | Persistent cross-session memory store                                                 |
| `aws_bedrockagentcore_memory_strategy` | `memory.tf`     | SUMMARIZATION strategy (optional)                                                     |
| `aws_ecr_repository`                   | `ecr.tf`        | ECR repository for the arm64 image                                                    |
| `aws_ecr_lifecycle_policy`             | `ecr.tf`        | Retains the last N images, expires older ones                                         |
| `aws_iam_role`                         | `iam.tf`        | Execution role for the AgentCore runtime                                              |
| `aws_iam_role_policy`                  | `iam.tf`        | Inline policy: CloudWatch, Bedrock, ECR, STS, Memory permissions              |
| `aws_cloudwatch_log_group`             | `cloudwatch.tf` | Structured audit log group for agent executions                                       |
| `null_resource` (docker build)         | `docker.tf`     | Builds and pushes the arm64 image on source changes                                   |


## File Layout

```
terraform/
├── agentcore.tf   – AgentCore runtime: container, network, env vars
├── memory.tf      – AgentCore Memory resource + summarization strategy
├── iam.tf         – IAM execution role and inline policy
├── ecr.tf         – ECR repository and lifecycle policy
├── docker.tf      – Content-addressable Docker build & ECR push
├── cloudwatch.tf  – CloudWatch log group for agent audit logs
├── locals.tf      – All derived identifiers and composed strings
├── variables.tf   – Input variables with defaults and descriptions
├── outputs.tf     – Exported identifiers for downstream use
└── providers.tf   – Terraform version constraint and AWS provider
```


## Prerequisites

| Tool         | Minimum version   | Notes                                                |
|--------------|-------------------|------------------------------------------------------|
| Terraform    | 1.5.0             | `tfenv` or direct download                           |
| AWS provider | 6.17.0            | Fetched automatically by `terraform init`            |
| AWS CLI      | v2                | Credentials must allow Bedrock, ECR, IAM, CloudWatch |
| Docker       | 24+ with `buildx` | Required for the arm64 image build in `docker.tf`    |

AWS credentials must have permissions to create the resources listed above.


## Usage

```bash
cd terraform/

# Download providers
terraform init

# Preview changes
terraform plan

# Deploy all resources (includes Docker build & push)
terraform apply

# Tear down
terraform destroy
```

Useful overrides:

```bash
# Use a different region and model
terraform apply \
  -var="region=us-east-1" \
  -var="model_id=amazon.nova-pro-v1:0"

# Force a new Docker image without changing source code
terraform apply -var="image_tag=$(git rev-parse --short HEAD)"
```


## Variables

| Variable                      | Type     | Default                       | Description                                                                                          |
|-------------------------------|----------|-------------------------------|------------------------------------------------------------------------------------------------------|
| `region`                      | `string` | `us-west-2`                   | AWS region for all resources                                                                         |
| `agent_name`                  | `string` | `cwlogs_diagnoser`            | Logical name; drives resource naming                                                                 |
| `model_id`                    | `string` | `us.amazon.nova-premier-v1:0` | Bedrock model or cross-region inference profile                                                      |
| `ecr_repo_name`               | `string` | `cwlogs-agentcore`            | ECR repository name                                                                                  |
| `image_tag`                   | `string` | `latest`                      | Docker image tag built and registered                                                                |
| `ecr_keep_last`               | `number` | `30`                          | Max images retained in ECR before expiry                                                             |
| `max_result_chars`            | `number` | `20000`                       | Hard cap on bytes per tool result (passed as env var)                                                |
| `memory_actor_id`             | `string` | `sre-agent`                   | Actor namespace for memory isolation                                                                 |
| `enable_memory_summarization` | `bool`   | `true`                        | Attach a SUMMARIZATION strategy to the Memory resource                                               |
| `memory_event_expiry_days`    | `number` | `7`                           | Days before Memory events expire automatically                                                       |
| `agent_log_group_name`        | `string` | `""`                          | Override log group name. Defaults to `/aws/bedrock-agentcore/<agent_name>`                           |
| `agent_log_retention_days`    | `number` | `1`                           | Retention period in days for the agent execution log group                                           |


## Outputs

| Output                      | Description                                           |
|-----------------------------|-------------------------------------------------------|
| `ecr_repository_url`        | Full ECR repository URL for further image pushes      |
| `image_uri`                 | Exact image URI registered with the AgentCore runtime |
| `agent_runtime_arn`         | ARN used by `invoke_agent.py` to call the runtime     |
| `runtime_role_arn`          | IAM role ARN assumed by the AgentCore runtime         |
| `memory_id`                 | AgentCore Memory resource ID passed to the container  |
| `agent_execution_log_group` | CloudWatch log group name for agent audit logs        |

Retrieve outputs after apply:

```bash
terraform output agent_runtime_arn
terraform output -json   # all outputs as JSON
```


## Notes

### arm64 requirement
AgentCore runtimes run on arm64 only. `docker.tf` passes `--platform linux/arm64` to `buildx`. Cross-compilation from x86 machines requires QEMU (installed automatically by Docker Desktop on macOS/Windows).

### Content-addressable builds
`docker.tf` hashes the Dockerfile, `pyproject.toml`, and key source files as Terraform `triggers`. The image is rebuilt and pushed **only when those files change**, preventing unnecessary rebuilds on unrelated `terraform apply` runs.

### State management
No backend is configured; state is stored locally (`terraform.tfstate`). For team use, configure an S3 + DynamoDB remote backend before running `terraform init`.

### Provider version
`aws_bedrockagentcore_agent_runtime` and `aws_bedrockagentcore_memory` require AWS provider **≥ 6.17.0**. Earlier versions will fail with an unknown resource type error.
