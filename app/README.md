# CW SRE Agent — Application

Conversational SRE incident-troubleshooting agent powered by:

- **Strands Agents SDK** — agentic loop, tool discovery, conversation management
- **AWS Bedrock** — Amazon Nova Premier / Nova Pro
- **AWS Bedrock AgentCore** — managed runtime and persistent memory
- **CloudWatch MCP server** — `awslabs.cloudwatch-mcp-server` (Logs Insights, metrics, alarms)

> **Back to root:** [../README.md](../README.md) | **Infrastructure:** [../terraform/README.md](../terraform/README.md)


## Table of Contents

1. [Local Quick Start](#local-quick-start)
2. [Environment Variables](#environment-variables)
3. [Interactive Commands](#interactive-commands)
4. [Invoke Remote Runtime](#invoke-remote-runtime)
5. [Build & Push to ECR](#build--push-to-ecr)
6. [Source Layout](#source-layout)
7. [MCP Server](#mcp-server)
8. [Cross-Account Access](#cross-account-access)
9. [Logging](#logging)
10. [Exported Bundles](#exported-bundles)


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


## Interactive Commands

| Command               | Description                                     |
|-----------------------|-------------------------------------------------|
| `/help`               | Show command reference                          |
| `/reset`              | Clear conversation and restart                  |
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
├── __init__.py       – Package version
├── __main__.py       – Package entry-point
├── cli.py            – Click CLI + REPL loop
├── agent.py          – Strands Agent factory + system prompt builder
├── config.py         – Environment variable loading and validation
├── server.py         – FastAPI HTTP server (AgentCore runtime entry-point)
├── logging.py        – JSON structured logging → stdout + CloudWatch
├── memory.py         – AgentCore Memory: save, recall, summarize
├── export.py         – Investigation bundle export to JSON
└── aws/
    ├── __init__.py
    ├── assume_role.py    – sts:AssumeRole factory with session caching
    └── session_cache.py  – TTL-based credential cache (55 min TTL)
```


## MCP Server

Tools are discovered dynamically at runtime via the MCP `tools/list` protocol.  
Tool names are **never hardcoded** — adding or renaming tools in a server update is reflected automatically.

| Package                         | Capabilities                                      |
|---------------------------------|---------------------------------------------------|
| `awslabs.cloudwatch-mcp-server` | CloudWatch Logs Insights queries, metrics, alarms |

The MCP server is installed as a pip dependency (see `pyproject.toml`) and started as a
stdio subprocess via Strands `MCPClient` wrapping `mcp.client.stdio.stdio_client`.
For cross-account access, assumed-role credentials are injected as `AWS_*` environment
variables into the subprocess.


## Cross-Account Access

When a user provides an IAM role ARN in the conversation, the agent:

1. Detects the `arn:aws:iam::<account_id>:role/<name>` pattern from message history.
2. Calls `sts:AssumeRole` via `AssumeRoleSessionFactory` and caches credentials with a 55-minute TTL.
3. Recreates the MCP client with the new credentials injected as environment variables.

Required trust policy in each **target account**:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "logs:StartQuery",
      "logs:GetQueryResults",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "cloudwatch:GetMetricData"
    ],
    "Resource": "*"
  }]
}
```


## Logging

Every turn is logged as a JSON object to:
- **stdout** (always, picked up by AgentCore's built-in log stream)

Logged fields include: `correlation_id`, `session_id`, `user_prompt`,
`tool_calls`, `tool_outputs`, `final_answer`, `exceptions`, `regions`, `account_ids`.


## Exported Bundles

Use `/export` or `--export` to write a JSON bundle containing:
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
