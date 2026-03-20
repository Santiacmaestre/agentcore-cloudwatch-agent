"""server.py – HTTP server entrypoint for AWS Bedrock AgentCore runtime.

Simplified with Strands Agents SDK: the manual Bedrock Converse loop,
MCP tool management, and tool execution are all handled by the SDK.

AgentCore communicates with the container over HTTP:
    POST /  with JSON body {"inputText": "..."}
    Headers include: x-amz-bedrock-agentcore-session-id

Run locally:
    uvicorn cw_sre_agent.server:app --host 0.0.0.0 --port 8080 --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import traceback
import uuid
from typing import Any, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.tools.mcp import MCPClient

from cw_sre_agent.agent import build_system_prompt, create_mcp_client
from cw_sre_agent.aws.assume_role import AssumeRoleSessionFactory
from cw_sre_agent.aws.session_cache import get_default_cache
from cw_sre_agent.config import load_config
from cw_sre_agent.export import BundleBuilder
from cw_sre_agent.logging import AgentLogger, LogContext
from cw_sre_agent.memory import AgentMemory
from cw_sre_agent.remediation import log_to_remediation

# ── Bootstrap config once at import time ─────────────────────────────────────

config = load_config()

# ── Suppress /ping, /health, and raw TCP health-check noise from logs ─────────


class _SuppressProbeLogs(logging.Filter):
    _PROBES = ("/ping", "/health")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(probe in msg for probe in self._PROBES)


class _SuppressInvalidHttpWarning(logging.Filter):
    """Suppress 'Invalid HTTP request received' from AgentCore TCP health checks."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "Invalid HTTP request received" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_SuppressProbeLogs())
logging.getLogger("uvicorn.error").addFilter(_SuppressInvalidHttpWarning())

# ── In-process session store ──────────────────────────────────────────────────
_SESSIONS: dict[str, dict[str, Any]] = {}

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="CW SRE Agent (Strands)", version="0.2.0")


# ── Input normalisation ──────────────────────────────────────────────────────

_LOG_GROUP_ARN_WILDCARD_RE = re.compile(
    r"(arn:aws(?:-cn|-us-gov)?:logs:[^:]+:\d{12}:log-group:[^:]+):\*"
)

_ROLE_ARN_RE = re.compile(
    r"arn:aws(?:-cn|-us-gov)?:iam::(\d{12}):role/[\w+=,.@/-]{1,512}"
)


def _normalize_user_text(text: str) -> str:
    """Strip :* wildcard suffix from CloudWatch log group ARNs."""
    return _LOG_GROUP_ARN_WILDCARD_RE.sub(r"\1", text)


# ── Cross-account role detection ─────────────────────────────────────────────


def _detect_role_arn(session: dict[str, Any]) -> tuple[Optional[str], str]:
    """Scan conversation for an IAM role ARN. Returns (role_arn, account_id)."""
    role_arn: Optional[str] = session.get("cross_account_role")
    account_id: str = session.get("cross_account_account_id", "")

    if role_arn:
        return role_arn, account_id

    for msg in reversed(session.get("messages_raw", [])):
        if msg.get("role") != "user":
            continue
        match = _ROLE_ARN_RE.search(msg.get("text", ""))
        if match:
            role_arn = match.group(0)
            account_id = match.group(1)
            session["cross_account_role"] = role_arn
            session["cross_account_account_id"] = account_id
            return role_arn, account_id

    return None, ""


def _assume_role_env(
    role_arn: Optional[str],
    account_id: str,
    logger: AgentLogger,
) -> dict[str, str]:
    """Assume cross-account role and return env vars, or empty dict."""
    if not role_arn:
        return {}

    for attempt in range(1, 4):
        try:
            factory = AssumeRoleSessionFactory(logger=logger)
            env_vars = factory.build_env_vars(
                account_id=account_id,
                role_arn=role_arn,
                region=config.aws_region,
            )
            return env_vars
        except Exception as exc:
            logger.warning("assume_role_attempt_failed", exc=exc, attempt=attempt)
            get_default_cache().invalidate(role_arn, config.aws_region)

    return {}


# ── Session management ────────────────────────────────────────────────────────


def _get_or_create_session(session_id: str) -> dict[str, Any]:
    """Return existing session or create a new one with a Strands Agent."""
    if session_id not in _SESSIONS:
        log_ctx = LogContext(session_id=session_id)
        logger = AgentLogger(
            context=log_ctx,
            aws_region=config.aws_region,
            log_group=config.agent_log_group,
            debug_mode=config.debug_mode,
            max_result_chars=config.max_result_chars,
        )

        # Create Strands model + MCP client + agent
        model = BedrockModel(
            model_id=config.effective_model_id,
            region_name=config.aws_region,
        )

        mcp_client = create_mcp_client()

        agent = Agent(
            model=model,
            tools=[mcp_client],
            system_prompt=build_system_prompt(config),
        )

        _SESSIONS[session_id] = {
            "agent": agent,
            "mcp_client": mcp_client,
            "log_ctx": log_ctx,
            "logger": logger,
            "messages_raw": [],
            "bundle": BundleBuilder(
                session_id=session_id,
                model_id=config.effective_model_id,
                aws_region=config.aws_region,
            ),
            "turn_lock": asyncio.Lock(),
            "last_user_text": "",
            "last_answer": "",
            "cross_account_env_key": (),
        }
        logger.info("session_created", session_id=session_id)

    return _SESSIONS[session_id]


async def _ensure_cross_account(session: dict[str, Any]) -> None:
    """If a role ARN is detected, recreate the MCP client with assumed creds."""
    logger: AgentLogger = session["logger"]
    role_arn, account_id = _detect_role_arn(session)
    cross_account_env = _assume_role_env(role_arn, account_id, logger)
    env_key = tuple(sorted(cross_account_env.items()))

    if env_key != session["cross_account_env_key"] and cross_account_env:
        logger.info("mcp_reconnect_cross_account", account_id=account_id)

        old_mcp: MCPClient = session["mcp_client"]
        try:
            old_mcp.stop()
        except Exception:
            pass

        new_mcp = create_mcp_client(cross_account_env)
        agent: Agent = session["agent"]

        model = BedrockModel(
            model_id=config.effective_model_id,
            region_name=config.aws_region,
        )
        session["agent"] = Agent(
            model=model,
            tools=[new_mcp],
            system_prompt=build_system_prompt(config),
            messages=agent.messages,
        )
        session["mcp_client"] = new_mcp
        session["cross_account_env_key"] = env_key


# ── Thinking tag stripper ─────────────────────────────────────────────────────

_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    return _THINKING_RE.sub("", text).strip()


# ── Agent turn ────────────────────────────────────────────────────────────────


async def _run_agent_turn(session: dict[str, Any], user_text: str) -> str:
    """Process one user message through Strands Agent. Returns the answer."""
    logger: AgentLogger = session["logger"]
    log_ctx: LogContext = session["log_ctx"]
    bundle: BundleBuilder = session["bundle"]
    agent: Agent = session["agent"]

    log_ctx.new_request()
    logger.log_user_prompt(user_text)
    bundle.add_turn("user", user_text, correlation_id=log_ctx.correlation_id)
    session["messages_raw"].append({"role": "user", "text": user_text})

    await _ensure_cross_account(session)

    # Refresh system prompt (contains current UTC time)
    agent.system_prompt = build_system_prompt(config)

    try:
        # Strands handles the entire agentic loop
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: agent(user_text),
        )
        final_answer = _strip_thinking(str(result))
    except Exception as exc:
        logger.error("agent_turn_error", exc=exc)
        final_answer = f"Error: {exc}"

    logger.log_final_answer(final_answer)
    bundle.add_turn("assistant", final_answer, correlation_id=log_ctx.correlation_id)

    # Write investigation events to the remediation log group
    now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log_to_remediation({
        "level": "INFO",
        "event": "user_prompt",
        "session_id": log_ctx.session_id,
        "correlation_id": log_ctx.correlation_id,
        "ts": now_str,
        "user_prompt": user_text,
    })
    log_to_remediation({
        "level": "INFO",
        "event": "final_answer",
        "session_id": log_ctx.session_id,
        "correlation_id": log_ctx.correlation_id,
        "ts": now_str,
        "final_answer": final_answer,
    })
    session["messages_raw"].append({"role": "assistant", "text": final_answer})

    # Persist to AgentCore Memory (best-effort)
    try:
        memory = AgentMemory(
            memory_id=config.memory_id,
            actor_id=config.memory_actor_id,
            region=config.aws_region,
            logger=logger,
        )
        memory.save_turn(log_ctx.session_id, "user", user_text,
                         {"correlation_id": log_ctx.correlation_id})
        memory.save_turn(log_ctx.session_id, "assistant", final_answer,
                         {"correlation_id": log_ctx.correlation_id})
    except Exception:
        pass

    return final_answer


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": config.effective_model_id}


@app.get("/ping")
async def ping() -> Response:
    return Response(status_code=200)


@app.post("/invocations")
async def invocations(request: Request) -> Response:
    return await handle_invoke(request)


@app.post("/")
async def handle_invoke(request: Request) -> Response:
    """Main invocation endpoint for AgentCore."""
    try:
        body = await request.body()
        data = json.loads(body.decode("utf-8")) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    session_id = (
        data.get("sessionId")
        or request.headers.get("x-amz-bedrock-agentcore-session-id")
        or request.headers.get("x-amzn-bedrock-agentcore-session-id")
        or str(uuid.uuid4())
    )

    user_text = (
        data.get("inputText")
        or data.get("prompt")
        or data.get("message")
        or data.get("text")
        or ""
    ).strip()

    if not user_text:
        return JSONResponse(
            status_code=400,
            content={"error": "Body must contain 'inputText' with the user message"},
        )

    user_text = _normalize_user_text(user_text)
    session = _get_or_create_session(session_id)

    # Fast path: identical re-submission → cached answer
    if user_text == session["last_user_text"] and session["last_answer"]:
        return JSONResponse(content={"outputText": session["last_answer"], "sessionId": session_id})

    turn_lock: asyncio.Lock = session["turn_lock"]
    async with turn_lock:
        if user_text == session["last_user_text"] and session["last_answer"]:
            return JSONResponse(content={"outputText": session["last_answer"], "sessionId": session_id})

        try:
            answer = await _run_agent_turn(session, user_text)
        except Exception as exc:
            tb = traceback.format_exc()
            session["logger"].error("unhandled_error", exc=exc)
            return JSONResponse(status_code=500, content={"error": str(exc), "trace": tb})

        session["last_user_text"] = user_text
        session["last_answer"] = answer

    return JSONResponse(content={"outputText": answer, "sessionId": session_id})
