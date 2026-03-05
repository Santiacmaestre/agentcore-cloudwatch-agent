# agentcore-devops-agent

Proof-of-concept SRE incident-troubleshooting agent built on **Amazon Bedrock AgentCore**.  
The agent uses a conversational CLI to investigate CloudWatch Logs, metrics, alarms, Application Signals SLOs, and CloudTrail events across multiple AWS accounts and regions — all without hardcoding a single tool name.


## Overview

| Layer               | Technology                                                |
|---------------------|-----------------------------------------------------------|
| LLM                 | Amazon Nova Premier / Nova Pro via Bedrock Converse API   |
| Runtime             | Amazon Bedrock AgentCore (arm64 container)                |
| Persistent memory   | AgentCore Memory with session-scoped summarization        |
| Observability tools | awslabs MCP servers (CloudWatch, App Signals, CloudTrail) |
| Infrastructure      | Terraform (AWS provider ≥ 6.17)                           |
| Application         | Python 3.12+ packaged with `uv`                           |


## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Developer / CI                                                     │
│  terraform apply  ──►  ECR (arm64 image)  ──►  AgentCore Runtime    │
└─────────────────────────────────────────────────────────────────────┘
                                                        │
                          ┌─────────────────────────────▼──────────────┐
                          │           AgentCore Runtime                │
                          │  ┌──────────────────────────────────────┐  │
                          │  │  Python container (cw_sre_agent)     │  │
                          │  │  ┌──────────┐  ┌───────────────────┐ │  │
                          │  │  │  CLI /   │  │  Bedrock Converse │ │  │
                          │  │  │  Wizard  │  │  (agentic loop)   │ │  │
                          │  │  └────┬─────┘  └─────────┬─────────┘ │  │
                          │  │       │                  │           │  │
                          │  │  ┌────▼──────────────────▼─────────┐ │  │
                          │  │  │         MCP Manager             │ │  │
                          │  │  │  CloudWatch · AppSignals · Trail│ │  │
                          │  │  └─────────────────────────────────┘ │  │
                          │  └──────────────────────────────────────┘  │
                          │                   │                        │
                          │  AgentCore Memory (cross-session recall)   │
                          └────────────────────────────────────────────┘
                                              │
                          ┌───────────────────▼───────────────────────┐
                          │  Target AWS Accounts (via sts:AssumeRole) │
                          │  CloudWatch Logs · Metrics · CloudTrail   │
                          │  Application Signals SLOs                 │
                          └───────────────────────────────────────────┘
```


## Repository Layout

```
agentcore-devops-agent/
├── app/                      # Python agent application
│   ├── src/cw_sre_agent/     # Agent source code
│   ├── scripts/              # build_and_push.sh, run_local.sh
│   ├── Dockerfile            # arm64 container image
│   ├── invoke_agent.py       # Remote runtime invocation helper
│   ├── pyproject.toml        # Package metadata & dependencies
│   └── README.md             # → Application guide
└── terraform/                # Infrastructure as code
    ├── agentcore.tf          # AgentCore runtime resource
    ├── memory.tf             # AgentCore Memory + summarization strategy
    ├── iam.tf                # Execution role & inline policy
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

### 1. Provision infrastructure

```bash
cd terraform/
terraform init
terraform apply
```

`terraform apply` will:
- Create an ECR repository
- Build & push the arm64 Docker image
- Provision an AgentCore runtime wired to Bedrock
- Create an AgentCore Memory resource with summarization
- Set up CloudWatch log group and IAM execution role

See [terraform/README.md](terraform/README.md) for all variables and outputs.

### 2. Run the agent

**Remote** (via the deployed AgentCore runtime):

```bash
cd app/
# ARN is discovered automatically from terraform output
python invoke_agent.py --interactive
```

**Local** (for development):

```bash
cd app/
cp .env.example .env   # fill in AWS_REGION, MODEL_ID, MEMORY_ID, MEMORY_ACTOR_ID
./scripts/run_local.sh
```

See [app/README.md](app/README.md) for the full wizard walkthrough, interactive commands, cross-account setup, and build instructions.


## Key Design Decisions

- **No hardcoded tool names** – the MCP manager discovers all tools dynamically via `tools/list`, so server updates are reflected automatically.
- **Cross-account via STS** – assumed-role credentials are injected as environment variables into each MCP subprocess, keeping the agent in the trusted account.
- **arm64 only** – AgentCore runtimes run exclusively on arm64; the Docker build uses `buildx --platform linux/arm64`.
- **Content-addressable Docker builds** – `docker.tf` hashes source files as Terraform triggers so the image is only rebuilt when code actually changes.


## License

See [LICENSE](LICENSE).
