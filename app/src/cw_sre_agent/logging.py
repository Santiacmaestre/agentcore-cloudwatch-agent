"""logging.py – JSON-structured logging to stdout + CloudWatch Logs destination.

Every log record is a JSON object written on a single line, making it
trivially machine-parseable and compatible with CloudWatch Logs Insights.

Design:
    - ``AgentLogger`` is the main façade used throughout the application.
    - All records include ``correlation_id`` (per-request UUID) and
      ``session_id`` (per-session UUID set at wizard completion).
    - Records are simultaneously written to:
        1) stdout / AgentCore's built-in log stream (always)
        2) an optional CloudWatch Log Group (when ``log_group`` is provided),
           using the session_id as the log stream name.

Log levels used:
    INFO  – normal flow (wizard steps, agent turns, tool calls)
    DEBUG – verbose detail (raw tool outputs, full prompts) when DEBUG_MODE=true
    ERROR – exceptions with full stacktrace strings
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError


# ── Constants ────────────────────────────────────────────────────────────────

LOG_SEQUENCE_TOKEN_CACHE: dict[str, str] = {}   # stream_name → sequenceToken

_TRUNCATE_SUFFIX = " … [TRUNCATED]"


# ── Helper ───────────────────────────────────────────────────────────────────

def _truncate(value: Any, max_chars: int) -> Any:
    """If *value* is a string longer than *max_chars*, truncate it."""
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + _TRUNCATE_SUFFIX
    return value


# ── Context holder ───────────────────────────────────────────────────────────

@dataclass
class LogContext:
    """Mutable context shared across a single agent session/request."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # populated after wizard completes
    account_ids: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    log_groups: dict[str, list[str]] = field(default_factory=dict)  # region -> [groups]
    time_window: dict[str, str] = field(default_factory=dict)       # {start, end}
    role_arns: dict[str, str] = field(default_factory=dict)         # account -> arn

    def new_request(self) -> None:
        """Rotate the correlation_id for a new LLM turn."""
        self.correlation_id = str(uuid.uuid4())


# ── CloudWatch sink ──────────────────────────────────────────────────────────

class CloudWatchLogsSink:
    """Sends log events to a CloudWatch Logs stream (session_id as stream name).

    Creates the log stream on first use.  Retries once on
    ``InvalidSequenceTokenException``.
    """

    def __init__(
        self,
        log_group: str,
        session_id: str,
        region: str,
        boto_session: Optional[boto3.Session] = None,
    ) -> None:
        self._log_group = log_group
        self._stream = session_id
        self._region = region
        self._client = (boto_session or boto3).client("logs", region_name=region)
        self._sequence_token: Optional[str] = None
        self._ready = False
        self._buffer: list[dict] = []   # events queued before stream is created

    def _ensure_stream(self) -> None:
        if self._ready:
            return
        try:
            self._client.create_log_stream(
                logGroupName=self._log_group,
                logStreamName=self._stream,
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceAlreadyExistsException":
                # Best-effort: if we can't create the stream, log to stderr and continue
                print(f"[CW-SINK WARN] could not create log stream: {exc}", file=sys.stderr)
                return
        self._ready = True

    def emit(self, record_dict: dict) -> None:
        """Send a single JSON record to CloudWatch Logs."""
        self._ensure_stream()
        if not self._ready:
            return  # skip if stream unavailable

        event = {
            "timestamp": int(time.time() * 1000),
            "message": json.dumps(record_dict, default=str),
        }

        kwargs: dict[str, Any] = {
            "logGroupName": self._log_group,
            "logStreamName": self._stream,
            "logEvents": [event],
        }
        if self._sequence_token:
            kwargs["sequenceToken"] = self._sequence_token

        try:
            resp = self._client.put_log_events(**kwargs)
            self._sequence_token = resp.get("nextSequenceToken")
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("InvalidSequenceTokenException", "DataAlreadyAcceptedException"):
                # Retry with the correct token
                self._sequence_token = exc.response["Error"].get("expectedSequenceToken")
                if self._sequence_token:
                    kwargs["sequenceToken"] = self._sequence_token
                    try:
                        resp = self._client.put_log_events(**kwargs)
                        self._sequence_token = resp.get("nextSequenceToken")
                    except ClientError:
                        pass  # best-effort
            else:
                print(f"[CW-SINK WARN] put_log_events failed: {exc}", file=sys.stderr)


# ── Main logger ──────────────────────────────────────────────────────────────

class AgentLogger:
    """Thread-safe JSON logger with dual output: stdout + CloudWatch.

    Usage::

        logger = AgentLogger(context, config)
        logger.info("tool_call", tool="run_query", params={"q": "..."})
        logger.error("exception", exc=e)
    """

    def __init__(
        self,
        context: LogContext,
        aws_region: str,
        log_group: Optional[str] = None,
        debug_mode: bool = False,
        max_result_chars: int = 20_000,
        boto_session: Optional[boto3.Session] = None,
    ) -> None:
        self._ctx = context
        self._debug = debug_mode
        self._max_chars = max_result_chars

        self._cw_sink: Optional[CloudWatchLogsSink] = (
            CloudWatchLogsSink(
                log_group=log_group,
                session_id=context.session_id,
                region=aws_region,
                boto_session=boto_session,
            )
            if log_group
            else None
        )

        # stdlib logger for stdout only
        self._stdout_logger = logging.getLogger("cw_sre_agent")
        if not self._stdout_logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._stdout_logger.addHandler(handler)
        self._stdout_logger.setLevel(logging.DEBUG if debug_mode else logging.INFO)
        self._stdout_logger.propagate = False

    def _build_record(self, event: str, level: str, extra: dict) -> dict:
        record: dict[str, Any] = {
            "level": level,
            "event": event,
            "session_id": self._ctx.session_id,
            "correlation_id": self._ctx.correlation_id,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        # Attach wizard-populated metadata when available
        if self._ctx.regions:
            record["regions"] = self._ctx.regions
        if self._ctx.account_ids:
            record["account_ids"] = self._ctx.account_ids
        if self._ctx.time_window:
            record["time_window"] = self._ctx.time_window

        # Truncate large string values in extra
        for k, v in extra.items():
            record[k] = _truncate(v, self._max_chars) if isinstance(v, str) else v

        return record

    def _emit(self, record: dict, level: str) -> None:
        line = json.dumps(record, default=str)
        lvl = getattr(logging, level.upper(), logging.INFO)
        self._stdout_logger.log(lvl, line)
        if self._cw_sink is not None:
            self._cw_sink.emit(record)

    # ── Public API ───────────────────────────────────────────────────────────

    def info(self, event: str, **extra: Any) -> None:
        self._emit(self._build_record(event, "INFO", extra), "INFO")

    def debug(self, event: str, **extra: Any) -> None:
        if self._debug:
            self._emit(self._build_record(event, "DEBUG", extra), "DEBUG")

    def warning(self, event: str, **extra: Any) -> None:
        self._emit(self._build_record(event, "WARNING", extra), "WARNING")

    def error(self, event: str, exc: Optional[BaseException] = None, **extra: Any) -> None:
        if exc is not None:
            extra["exception"] = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        self._emit(self._build_record(event, "ERROR", extra), "ERROR")

    def log_user_prompt(self, prompt: str) -> None:
        self.info("user_prompt", user_prompt=prompt)

    def log_final_answer(self, answer: str) -> None:
        self.info("final_answer", final_answer=answer)

    def log_tool_call(self, tool_name: str, params: dict) -> None:
        self.info("tool_call", tool=tool_name, params=params)

    def log_tool_output(self, tool_name: str, output: Any) -> None:
        self.debug("tool_output", tool=tool_name, output=output)

    def log_wizard_state(self, state: dict) -> None:
        self.info("wizard_state_snapshot", wizard_state=state)
