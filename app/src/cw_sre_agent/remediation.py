"""remediation.py – Writes agent investigation results to a dedicated CloudWatch Log Group.

Each agent turn (user prompt + final answer) is logged as structured JSON events,
preserving a full history of all investigations and remediation recommendations.
"""

from __future__ import annotations

import os

from cw_sre_agent.logging import CloudWatchLogsSink


_LOG_STREAM_NAME = "remediation-actions"
_sink: CloudWatchLogsSink | None = None


def _get_sink() -> CloudWatchLogsSink | None:
    """Lazy-init a CloudWatch sink for the remediation log group."""
    global _sink
    if _sink is not None:
        return _sink

    log_group = os.environ.get("REMEDIATION_LOG_GROUP")
    if not log_group:
        return None

    region = os.environ.get("AWS_REGION", "us-west-2")
    _sink = CloudWatchLogsSink(
        log_group=log_group,
        session_id=_LOG_STREAM_NAME,
        region=region,
    )
    return _sink


def log_to_remediation(record: dict) -> None:
    """Append a structured JSON event to the remediation log group."""
    sink = _get_sink()
    if sink:
        sink.emit(record)
