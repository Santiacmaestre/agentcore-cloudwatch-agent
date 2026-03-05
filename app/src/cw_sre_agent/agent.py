"""agent.py – Strands-based SRE agent factory.

Replaces the manual Bedrock Converse loop + MCP tool management with the
Strands Agents SDK.  The entire agentic loop (tool discovery, tool execution,
retry logic, conversation history) is handled by Strands.

Usage::

    agent, mcp_client = create_sre_agent(config)
    response = agent("Analyze /aws/eks/cluster logs in us-east-1")
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.tools.mcp import MCPClient

from cw_sre_agent.config import Config


# ── System prompt builder ─────────────────────────────────────────────────────


def build_system_prompt(config: Config) -> str:
    """Build the system prompt with current UTC time for accurate time windows."""
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_default = (now_utc - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

    return f"""You are an expert SRE (Site Reliability Engineer) assistant powered by AWS observability tools.
You help engineers investigate and troubleshoot infrastructure incidents through natural conversation.

## CURRENT TIME
**The current UTC time is: {now_str}**
Use this as the anchor for ALL time calculations. "Last 24h" means from {start_default} to {now_str}.
NEVER query dates outside the window [{start_default}, {now_str}] unless the user explicitly provides
a different range. CloudWatch log groups typically have 7-day retention; querying older dates returns 0 results.

## Decision tree — follow this exactly, in order

### STEP 1 — Extract from current message AND full conversation history:
  A. AWS region                      (e.g. "us-west-2")
  B. CloudWatch Log Group name(s)    (e.g. "/aws/eks/my-cluster/cluster")
  C. Time window                     (e.g. "last 2 days", "últimas 48h") — DEFAULT to last 24h if not given
  D. Cross-account role ARN          (only needed when target account ≠ your account)

### STEP 2 — If you have A + B (and D when needed) → EXECUTE IMMEDIATELY
The objective is OPTIONAL. "Show me what's there", "tell me what you see", "analyse what's in the logs",
or no explicit objective at all are ALL valid — they mean: run a broad exploratory query and describe
everything you find (errors, warnings, patterns, notable events, volume trends).

Do NOT ask for a specific objective before running the query.
Do NOT ask the user to confirm parameters you already have.
Do NOT send ANY message before calling the tools — just call them.
Do NOT ask "¿Quieres detectar errores o analizar patrones?" — just do both.

### STEP 3 — A or B is missing → ask for the SINGLE missing item, nothing else
Ask one short question. Do not list what you already know. Do not ask for C or D at this stage.

### STEP 4 — No target at all → greet briefly, ask what they need
Only if the user has provided neither a log group nor an account/region context.

## STRICT RULES — violations break the assistant
- NEVER re-ask for information already present anywhere in the conversation history.
- NEVER enumerate a list of clarifying questions when you can proceed.
- NEVER open with "Para continuar, necesito:" when you already have A + B.
- NEVER ask "¿Confirmas el periodo de tiempo?" — use what was given or default to 24h.
- NEVER ask for an "objective" as a prerequisite to running a query.
- "Explícame qué ves" / "dime qué hay" / "show me what's there" = proceed with a broad query NOW.
- NEVER use dates from before {start_default} unless explicitly instructed by the user.
- NEVER fabricate a general explanation of "what logs usually contain" when a query returns 0 results.
  If a query returns empty, try once with the default 24h window before reporting.
  If still empty, report: "No hay eventos en las últimas 24h ({start_default} – {now_str}).
  El grupo tiene retención de N días — puede que no haya actividad reciente."
  Do NOT speculate about what the logs "would normally show". Do NOT tell the user to use the console.

## Execution behaviour
- Default start/end: `start={start_default}`, `end={now_str}` (last 24h).
- Default query: `fields @timestamp, @message | sort @timestamp desc | limit 200`
  Summarise patterns, errors, warnings and volume from the results.
- If results are empty for the last 24h, extend to 7 days (start = now-7d) in ONE retry.
  If still empty, stop and tell the user plainly.
- Break windows longer than 6 hours into 3-hour chunks for Insights queries.
- Correlate findings across log groups; present a clear summary with timestamps and severity.

## Runtime context
- AgentCore region: {config.aws_region}
- Model: {config.effective_model_id}
- Max result chars per tool: {config.max_result_chars}

## Language & tone
- Always respond in English, regardless of the language the user writes in.
- Write with correct spelling and grammar at all times.
- Include timestamps, severity levels, and actionable next steps in findings.
- Cross-account credentials are injected automatically into every MCP tool call.
- If a tool call fails with an access-denied error: report the exact STS/IAM error
  and state that the execution role may lack sts:AssumeRole permission.
- After returning findings, invite the user to drill deeper. NEVER close the conversation.
"""


# ── MCP client factory ────────────────────────────────────────────────────────


def create_mcp_client(
    cross_account_env: Optional[dict[str, str]] = None,
) -> MCPClient:
    """Create an MCPClient for the CloudWatch MCP server.

    Args:
        cross_account_env: AWS credential env vars to inject into the
                           MCP subprocess for cross-account access.

    Returns:
        An MCPClient ready to be passed to a Strands Agent.
    """
    env = dict(os.environ)
    if cross_account_env:
        env.update(cross_account_env)

    return MCPClient(
        lambda: stdio_client(StdioServerParameters(
            command="awslabs.cloudwatch-mcp-server",
            env=env,
        ))
    )


# ── Agent factory ─────────────────────────────────────────────────────────────


def create_sre_agent(
    config: Config,
    cross_account_env: Optional[dict[str, str]] = None,
    message_history: Optional[list[dict[str, Any]]] = None,
) -> tuple[Agent, MCPClient]:
    """Create a Strands Agent wired to the CloudWatch MCP server.

    Args:
        config:            Application configuration.
        cross_account_env: AWS credential env vars for cross-account access.
        message_history:   Optional existing conversation messages to resume.

    Returns:
        A (agent, mcp_client) tuple.  The caller must manage the MCPClient
        lifecycle via ``mcp_client.start()`` / ``mcp_client.stop()``.
    """
    model = BedrockModel(
        model_id=config.effective_model_id,
        region_name=config.aws_region,
    )

    mcp_client = create_mcp_client(cross_account_env)

    agent = Agent(
        model=model,
        tools=[mcp_client],
        system_prompt=build_system_prompt(config),
        messages=message_history or [],
    )

    return agent, mcp_client
