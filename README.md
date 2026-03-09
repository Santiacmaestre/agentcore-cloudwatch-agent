# agentcore-cloudwatch-agent

Proof-of-concept SRE incident-troubleshooting agent built on **Amazon Bedrock AgentCore**.
Automatically monitors CloudWatch Logs, detects errors, invokes the agent via a Lambda subscription filter watcher, and writes remediation actions directly to AWS Systems Manager Parameter Store.

Powered by **Anthropic Claude Sonnet 4.6** (via Bedrock), the **Strands Agents SDK**, and the CloudWatch MCP server.


## Overview

| Layer               | Technology                                                    |
|---------------------|---------------------------------------------------------------|
| LLM                 | Anthropic Claude Sonnet 4.6 via Strands Agents SDK            |
| Agentic framework   | Strands Agents SDK (`strands-agents`, `strands-agents-tools`) |
| Runtime             | Amazon Bedrock AgentCore (arm64 container)                    |
| Persistent memory   | AgentCore Memory with session-scoped summarization            |
| Observability tools | `awslabs.cloudwatch-mcp-server` (MCP over stdio)              |
| Log monitoring      | CloudWatch Logs Subscription Filter → Lambda watcher          |
| Remediation         | Agent writes directly to SSM Parameter Store (boto3)          |
| Infrastructure      | Terraform (AWS provider ≥ 6.17)                               |
| Application         | Python 3.12+ packaged with `uv`                               |


## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Developer / Infrastructure                                                  │
│  terraform apply  ──►  ECR (arm64 image)  ──►  AgentCore Runtime             │
│                                                        ▲ (manual invocation)  │
└────────────────────────────────────────────────────────┼─────────────────────┘
                                                         │
                    ┌─────────────────────────────────────┴──────────────────┐
                    │                                                        │
         ┌──────────▼──────────┐                    ┌──────────────────────┐ │
         │ CloudWatch Logs     │                    │  AgentCore Runtime   │ │
         │ /demo/app-logs      │                    │  ┌────────────────┐  │ │
         │ (mixed logs)        │                    │  │ Python Agent   │  │ │
         └──────────┬──────────┘                    │  │ + Strands SDK  │  │ │
                    │                               │  │ + CloudWatch   │  │ │
                    │ Subscription                  │  │   MCP Server   │  │ │
                    │ Filter (ERROR/CRITICAL)       │  │ + write_to_    │  │ │
                    │                               │  │   parameter_   │  │ │
                    ▼                               │  │   store tool   │  │ │
         ┌──────────────────────┐                   │  └────┬───────────┘  │ │
         │ log-watcher Lambda   │                   │       │ (boto3)      │ │
         │ - Filters ERROR logs │                   └───────┼──────────────┘ │
         │ - Writes summary     │──┐                        │                │
         │   to SSM             │  │                        │                │
         └──────────────────────┘  │                        ▼                │
                                   │   ┌────────────────────────────────────┐│
                                   │   │ SSM Parameter Store                ││
                                   │   │ /sre-agent/error-detected          ││
                                   └──►│ /sre-agent/actions/latest          ││
                                       │ {error_type, action, severity}     ││
                                       └────────────────────────────────────┘│
                                           AgentCore Memory (cross-session)  │
                                       └────────────────────────────────────┘
```


## Demo Flow

1. **Inject demo logs** – A script pushes ~150 log events (80% normal, 20% errors) to CloudWatch Logs
2. **Subscription filter triggers** – CloudWatch Logs subscription filter detects ERROR/CRITICAL level events
3. **log-watcher Lambda filters** – Lambda extracts error summary and writes to SSM (`/sre-agent/error-detected`)
4. **Agent invocation** – User manually invokes the agent via `run_demo.sh` to analyze logs (can be automated via EventBridge/SNS)
5. **Agent analyzes** – The SRE agent queries CloudWatch Logs, identifies patterns, counts, and severity
6. **Write remediation action** – Agent calls `write_to_parameter_store` (boto3 SSM PutParameter directly)
7. **Parameter Store updated** – Error details and recommended action written to `/sre-agent/actions/latest`
8. **Verification** – Check SSM parameter to see the findings

**Semi-automated flow:** Lambda detects and summarizes errors; user/automation triggers agent analysis.


## Repository Layout

```
agentcore-cloudwatch-agent/
├── app/                      # Python agent application
│   ├── src/cw_sre_agent/     # Agent source code
│   │   ├── remediation.py    # Strands tool: write_to_parameter_store (boto3 SSM)
│   │   └── ...               # agent, config, server, cli, etc.
│   ├── scripts/              # build_and_push.sh, run_local.sh
│   ├── Dockerfile            # arm64 container image
│   ├── invoke_agent.py       # Remote runtime invocation helper
│   ├── pyproject.toml        # Package metadata & dependencies
│   └── README.md             # → Application guide
├── lambda/                   # Lambda functions
│   └── log_watcher.py        # Subscription filter watcher → invokes AgentCore
├── scripts/                  # Demo scripts
│   ├── run_demo.sh           # End-to-end demo (inject logs → wait → verify)
│   └── inject_demo_logs.py   # Injects sample logs with errors
└── terraform/                # Infrastructure as code
    ├── agentcore.tf          # AgentCore runtime resource
    ├── log_watcher.tf        # log-watcher Lambda + IAM role
    ├── demo.tf               # Demo log group + subscription filter + SSM parameter
    ├── memory.tf             # AgentCore Memory + summarization strategy
    ├── iam.tf                # AgentCore execution role & inline policy
    ├── ecr.tf                # ECR repository + lifecycle policy
    ├── docker.tf             # null_resource: build & push on change
    ├── cloudwatch.tf         # CloudWatch log group
    ├── locals.tf             # Derived identifiers
    ├── variables.tf          # All input variables with defaults
    ├── outputs.tf            # Key resource identifiers
    └── README.md             # → Infrastructure guide
```


## Prerequisites

| Tool      | Minimum version   | Notes                                        |
|-----------|-------------------|----------------------------------------------|
| AWS CLI   | v2                | Must have ECR push & Bedrock permissions     |
| Docker    | 24+ with `buildx` | Required for arm64 cross-compilation         |
| Terraform | 1.5.0             | AWS provider ≥ 6.17 is fetched automatically |
| Python    | 3.12              | Only needed for local CLI usage              |
| `uv`      | latest            | Python package manager used in the app       |


## Getting Started

### Prerequisites

Ensure you have:
- **AWS CLI v2** with credentials configured (Bedrock API access required)
- **Docker 24+** with buildx support (`docker buildx version`)
- **Terraform 1.5+** (AWS provider ≥ 6.17 auto-fetched)
- **Python 3.12+** with pip/uv
- **AWS account** with Bedrock access in your region (default: `us-west-2`)

### 1. Provision infrastructure

```bash
cd terraform/
terraform init
terraform apply -var region=us-west-2
```

**What gets created:**
- ECR repository for arm64 agent image
- AgentCore runtime (Sonnet 4.6 via Bedrock)
- AgentCore Memory resource
- CloudWatch Logs demo group (`/demo/app-logs`)
- **log-watcher Lambda** (triggered by subscription filter)
- Subscription filter on demo logs (ERROR/CRITICAL pattern)
- SSM Parameter Store (`/sre-agent/actions/latest`)
- IAM roles for AgentCore runtime and Lambda

See [terraform/README.md](terraform/README.md) for all variables and outputs.

### 2. Run the demo

**Step A: Inject logs and trigger Lambda filter**
```bash
./scripts/run_demo.sh us-west-2
```

This script:
1. Injects ~150 mixed log events (80% normal, 20% errors) to `/demo/app-logs`
2. CloudWatch subscription filter detects ERROR/CRITICAL events
3. log-watcher Lambda writes error summary to SSM (`/sre-agent/error-detected`)
4. Shows the SSM error alert

**Step B: Manually invoke the agent** (can be automated via EventBridge/SNS)

Once the log-watcher Lambda has written the error summary, invoke the agent:

```bash
cd app/
# Get the runtime ARN from Terraform
RUNTIME_ARN=$(cd ../terraform && terraform output -raw agent_runtime_arn)

# Invoke the agent with a prompt to analyze the log group
python invoke_agent.py \
  --runtime-arn "$RUNTIME_ARN" \
  --prompt "Analyse the log group /demo/app-logs for the last 24 hours. Look for errors and trigger remediation."
```

The agent will:
- Query CloudWatch Logs Insights
- Identify error patterns and severity
- Call `write_to_parameter_store` to record findings in `/sre-agent/actions/latest`

### 3. Inspect results

```bash
# View the remediation action written by the agent
aws ssm get-parameter \
  --name /sre-agent/actions/latest \
  --region us-west-2 \
  --query 'Parameter.Value' \
  --output text | python3 -m json.tool
```

Expected output:
```json
{
  "timestamp": "2026-03-08T14:30:00Z",
  "error_type": "DatabaseConnectionError",
  "error_category": "database",
  "source_log_group": "/demo/app-logs",
  "summary": "Detected 15 DatabaseConnectionError events in /demo/app-logs over 24 hours; connection pool near saturation",
  "action": "scale_up_connections",
  "severity": "HIGH"
}
```

### 4. (Optional) Interactive agent use

For interactive conversations with the agent:

```bash
cd app/
# Discover runtime ARN from terraform outputs
RUNTIME_ARN=$(cd ../terraform && terraform output -raw agent_runtime_arn)
python invoke_agent.py --prompt "Analyse /demo/app-logs for the last 24 hours"
```

See [app/README.md](app/README.md) for more interactive commands and cross-account setup.


## Key Design Decisions

- **Anthropic Claude Sonnet 4.6** – top-tier reasoning model via Bedrock cross-region inference, no fallback to other models.
- **Filtered error detection** – CloudWatch Logs subscription filter detects ERROR/CRITICAL events automatically; Lambda watcher writes summaries to SSM for downstream consumption.
- **Direct SSM writes** – agent calls `write_to_parameter_store` (boto3 SSM PutParameter) directly, removing Lambda invocation intermediary. Faster, simpler, fewer failure points.
- **Manual agent invocation** – user or automation (via EventBridge/SNS) invokes the agent after log-watcher Lambda detects errors. Flexible, testable, doesn't require private endpoint access.
- **Strands Agents SDK** – the entire agentic loop (tool discovery, execution, retry, conversation history) is delegated to Strands, replacing manual Bedrock Converse API calls.
- **Dynamic tool discovery** – the Strands `MCPClient` discovers all tools via the MCP `tools/list` protocol, so CloudWatch MCP server updates are reflected automatically.
- **Cross-account via STS** – assumed-role credentials are injected as environment variables into the MCP subprocess, keeping the agent in the trusted account.
- **arm64 only** – AgentCore runtimes run exclusively on arm64; the Docker build uses `buildx --platform linux/arm64`.
- **Content-addressable Docker builds** – `docker.tf` hashes source files as Terraform triggers so the image is only rebuilt when code actually changes.
- **Cost optimization** – Lambda filters before invocation, so AgentCore is only called when errors exist.


## License

See [LICENSE](LICENSE).
