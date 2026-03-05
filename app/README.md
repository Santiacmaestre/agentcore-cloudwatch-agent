# CW SRE Agent — Application

Conversational SRE incident-troubleshooting agent powered by:

- **AWS Bedrock** — Amazon Nova Premier / Nova Pro via Converse API
- **AWS Bedrock AgentCore** — managed runtime and persistent memory
- **MCP servers** — CloudWatch, CloudWatch Application Signals, CloudTrail (official `awslabs` packages)

> **Back to root:** [../README.md](../README.md) | **Infrastructure:** [../terraform/README.md](../terraform/README.md)


## Table of Contents

1. [Local Quick Start](#local-quick-start)
2. [Environment Variables](#environment-variables)
3. [Pre-flight Wizard](#pre-flight-wizard)
4. [Interactive Commands](#interactive-commands)
5. [Invoke Remote Runtime](#invoke-remote-runtime)
6. [Build & Push to ECR](#build--push-to-ecr)
7. [Source Layout](#source-layout)
8. [MCP Servers](#mcp-servers)
9. [Cross-Account Access](#cross-account-access)


## Local Quick Start

### 1. Install dependencies

```bash
cd app/
pip install uv          # one-time
uv venv && source .venv/bin/activate
uv pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in the required values (see table below)
```

### 3. Run the CLI

```bash
# Via installed entry-point
cw-sre-agent

# Via Python module
python -m cw_sre_agent

# Via helper script (auto-sources .env)
./scripts/run_local.sh
```

### 4. Override the model at runtime

```bash
cw-sre-agent --model amazon.nova-pro-v1:0
```


## Environment Variables

### Required

| Variable          | Description                                                      |
|-------------------|------------------------------------------------------------------|
| `AWS_REGION`      | AgentCore runtime region (e.g. `us-east-1`)                      |
| `MODEL_ID`        | Bedrock model ID (e.g. `amazon.nova-premier-v1:0`)               |
| `MEMORY_ID`       | AgentCore Memory resource ID — from `terraform output memory_id` |
| `MEMORY_ACTOR_ID` | Actor namespace for memory isolation (e.g. `sre-agent`)          |

### Optional

| Variable           | Default | Description                              |
|--------------------|---------|------------------------------------------|
| `MAX_RESULT_CHARS` | `20000` | Soft cap on bytes returned per tool call |
| `DEBUG_MODE`       | `false` | Set `true` for verbose structured logs   |
| `AGENT_LOG_GROUP`  | —       | CloudWatch log group for audit logs      |


## Pre-flight Wizard

On every session start the agent runs a **10-step wizard** before any tool is invoked:

| Step | Input                                                                                        |
|------|----------------------------------------------------------------------------------------------|
| 1    | Session ID (auto-generated UUID or custom)                                                   |
| 2    | Timezone (default: `America/Bogota`)                                                         |
| 3    | Target AWS regions (mandatory, comma-separated)                                              |
| 4    | Log groups to query per region                                                               |
| 5    | Time window — absolute (`2026-03-01T10:00/11:00`) or relative (`last 2h`, `últimas 2 horas`) |
| 6    | Time-chunk strategy — window size + optional sampling                                        |
| 7    | Cross-account role mapping (`account_id → role_arn`)                                         |
| 8    | Analysis objectives (error patterns / CloudTrail / App Signals)                              |
| 9    | Output detail level (executive summary or full evidence)                                     |
| 10   | Confirmation before execution                                                                |

The agent will **not** call any tool until step 10 is confirmed.


## Interactive Commands

| Command               | Description                                     |
|-----------------------|-------------------------------------------------|
| `/help`               | Show command reference                          |
| `/reset`              | Clear conversation and restart the wizard       |
| `/summarize`          | Print memory summary for the current session    |
| `/recall <sessionId>` | Reload a previous session from AgentCore Memory |
| `/export`             | Export investigation bundle to `./exports/`     |
| `/quit` / `/exit`     | Exit the agent                                  |


## Invoke Remote Runtime

`invoke_agent.py` calls a deployed AgentCore runtime without running the container locally:

```bash
# Single prompt
python invoke_agent.py --prompt "Are there critical errors in us-east-1?"

# Interactive session
python invoke_agent.py --interactive

# Interactive session with export
python invoke_agent.py --interactive --export --export-dir ./exports
```

`AGENT_RUNTIME_ARN` is resolved in this order:

1. `AGENT_RUNTIME_ARN` environment variable
2. `.env` file in the current directory
3. `terraform output -json` — key `agent_runtime_arn`


## Build & Push to ECR

AgentCore requires `linux/arm64` images. The build script uses Docker `buildx`:

```bash
# Explicit arguments
./scripts/build_and_push.sh \
  --repo   123456789012.dkr.ecr.us-east-1.amazonaws.com/cw-sre-agent \
  --tag    latest \
  --region us-east-1

# Via environment variables
export ECR_REPO=123456789012.dkr.ecr.us-east-1.amazonaws.com/cw-sre-agent
export AWS_REGION=us-east-1
./scripts/build_and_push.sh
```

**Prerequisites:** Docker ≥ 24 with `buildx`, AWS CLI v2 with ECR push permissions.

> Terraform handles the build automatically via `docker.tf` on every `terraform apply` when source files change. Use this script only for manual image updates.


## Source Layout

```
src/cw_sre_agent/
├── __main__.py       – Package entry-point
├── cli.py            – Click CLI + REPL loop
├── wizard.py         – 10-step pre-flight wizard
├── agent.py          – Bedrock Converse agentic loop + tool dispatch
├── config.py         – Environment variable loading and validation
├── logging.py        – JSON structured logging → stdout + CloudWatch
├── timeparse.py      – Human/absolute time range parsing and chunking
├── memory.py         – AgentCore Memory: save, recall, summarize
├── export.py         – Investigation bundle export to JSON
├── server.py         – AgentCore runtime entry-point (HTTP server mode)
├── mcp/
│   ├── manager.py    – MCP server lifecycle + dynamic tool discovery
│   └── transport.py  – Stdio subprocess config for awslabs MCP servers
└── aws/
    ├── assume_role.py    – sts:AssumeRole factory with session caching
    └── session_cache.py  – TTL-based credential cache (55 min TTL)
```


## MCP Servers

All tools are discovered dynamically at runtime via the MCP `tools/list` protocol.  
Tool names are **never hardcoded** — adding or renaming tools in a server update is reflected automatically.

| Package                                            | Capabilities                                         |
|----------------------------------------------------|------------------------------------------------------|
| `awslabs.cloudwatch-mcp-server`                    | CloudWatch Logs Insights queries, metrics, alarms    |
| `awslabs.cloudwatch-applicationsignals-mcp-server` | Service health, SLOs, latency analysis               |
| `awslabs.cloudtrail-mcp-server`                    | API event history, infrastructure change correlation |

Each server is started with `uvx --quiet <package>` as a managed subprocess.  
For cross-account access, assumed-role credentials are injected as `AWS_*` environment variables.


## Cross-Account Access

The wizard accepts a mapping of `account_id → role_arn`.  
`AssumeRoleSessionFactory` calls `sts:AssumeRole` and caches credentials with a 55-minute TTL.  
MCP server subprocesses inherit the credentials via environment variables.

Required trust policy in each **target account**:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "logs:StartQuery",
      "logs:GetQueryResults",
      "cloudwatch:GetMetricData",
      "cloudtrail:LookupEvents",
      "application-signals:*"
    ],
    "Resource": "*"
  }]
}
```



## Logging

Every turn is logged as a JSON object to:
- **stdout** (always, picked up by AgentCore's built-in log stream)

Logged fields include: `correlation_id`, `session_id`, `user_prompt`, `wizard_state`,
`tool_calls`, `tool_outputs`, `final_answer`, `exceptions`, `regions`, `account_ids`.

Nothing is redacted.


## Exported Bundles

Use `/export` or `--export` to write a JSON bundle containing:
- Full wizard configuration
- All conversation turns
- All tool calls with parameters and outputs
- Findings and metadata

Files are saved as `cw-sre-bundle-<session_id[:8]>-<timestamp>.json`.


## Example `.env`

```dotenv
AWS_REGION=us-east-1
MODEL_ID=amazon.nova-premier-v1:0
MEMORY_ID=mem-xxxxxxxxxxxx
MEMORY_ACTOR_ID=sre-team
MAX_RESULT_CHARS=20000
DEBUG_MODE=false

# For invoke_agent.py
AGENT_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/xxxxxxxx
```
