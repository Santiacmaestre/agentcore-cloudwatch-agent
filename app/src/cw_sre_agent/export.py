"""export.py – Bundle export: saves all inputs, outputs and findings to disk.

Exports a JSON file containing:
    - wizard_state     (full configuration)
    - conversation     (all user/assistant turns)
    - tool_calls       (all tool invocations with params and outputs)
    - findings         (structured findings extracted from the agent)
    - metadata         (timestamps, model_id, region, session_id, etc.)

Nothing is redacted.  The user explicitly requested full fidelity.

File naming convention:
    cw-sre-bundle-<session_id>-<YYYYMMDD-HHMMSS>.json
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ToolCallRecord:
    tool_name: str
    params: dict
    output: str
    timestamp: str = field(default_factory=lambda: _now_iso())
    error: Optional[str] = None


@dataclass
class ConversationTurn:
    role: str           # "user" | "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: _now_iso())
    correlation_id: Optional[str] = None


@dataclass
class ExportBundle:
    """Container for a complete incident investigation bundle."""

    session_id: str
    created_at: str = field(default_factory=lambda: _now_iso())
    model_id: str = ""
    aws_region: str = ""
    wizard_state: dict = field(default_factory=dict)
    conversation: list[ConversationTurn] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Builder ───────────────────────────────────────────────────────────────────

class BundleBuilder:
    """Accumulates data throughout a session and produces an :class:`ExportBundle`."""

    def __init__(self, session_id: str, model_id: str = "", aws_region: str = "") -> None:
        self._bundle = ExportBundle(
            session_id=session_id,
            model_id=model_id,
            aws_region=aws_region,
        )

    def set_wizard_state(self, state_dict: dict) -> None:
        self._bundle.wizard_state = state_dict

    def add_turn(self, role: str, content: str, correlation_id: Optional[str] = None) -> None:
        self._bundle.conversation.append(
            ConversationTurn(role=role, content=content, correlation_id=correlation_id)
        )

    def add_tool_call(
        self,
        tool_name: str,
        params: dict,
        output: str,
        error: Optional[str] = None,
    ) -> None:
        self._bundle.tool_calls.append(
            ToolCallRecord(tool_name=tool_name, params=params, output=output, error=error)
        )

    def add_finding(self, finding: str) -> None:
        self._bundle.findings.append(finding)

    def set_metadata(self, **kwargs: Any) -> None:
        self._bundle.raw_metadata.update(kwargs)

    def build(self) -> ExportBundle:
        return self._bundle


# ── Writer ────────────────────────────────────────────────────────────────────

def export_bundle(
    bundle: ExportBundle,
    output_dir: str = ".",
    logger: Optional[object] = None,
) -> str:
    """Serialise *bundle* to a JSON file in *output_dir*.

    Returns the absolute path of the written file.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"cw-sre-bundle-{bundle.session_id[:8]}-{ts}.json"
    filepath = os.path.abspath(os.path.join(output_dir, filename))

    def _to_dict(obj: Any) -> Any:
        """Recursively convert dataclasses to dicts."""
        if hasattr(obj, "__dataclass_fields__"):
            return {k: _to_dict(v) for k, v in asdict(obj).items()}
        if isinstance(obj, list):
            return [_to_dict(i) for i in obj]
        if isinstance(obj, dict):
            return {k: _to_dict(v) for k, v in obj.items()}
        return obj

    payload = _to_dict(bundle)

    os.makedirs(output_dir, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)

    if logger is not None:
        logger.info(  # type: ignore[attr-defined]
            "bundle_exported",
            filepath=filepath,
            turns=len(bundle.conversation),
            tool_calls=len(bundle.tool_calls),
        )
    return filepath
