"""memory.py – Wrapper around AWS Bedrock AgentCore Memory API.

Provides save/load/list operations for conversation context keyed by
session_id and actor_id (the two dimensions of AgentCore Memory).

AgentCore Memory API (boto3 service: ``bedrock-agentcore``):
    - ``create_memory_session`` / ``get_memory_session_summary``
    - ``put_memory_records`` / ``list_memory_records``
    - The agent uses actor-level namespacing via MEMORY_ACTOR_ID.

Notes:
    - The MEMORY_ID comes from the Terraform resource
      ``aws_bedrockagentcore_memory.this.id``.
    - session_id from the wizard is used as the AgentCore "sessionId"
      parameter so each investigation session is independently recallable.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError


class AgentMemory:
    """Thin façade over the Bedrock AgentCore Memory API.

    Args:
        memory_id:   The AgentCore Memory resource ID (from env / Terraform).
        actor_id:    Actor namespace for memory isolation (from env).
        region:      AWS region for the Memory API endpoint.
        logger:      An :class:`~cw_sre_agent.logging.AgentLogger` instance.
        boto_session: Optional boto3 session (defaults to ambient credentials).
    """

    _SERVICE = "bedrock-agentcore"

    def __init__(
        self,
        memory_id: str,
        actor_id: str,
        region: str,
        logger: object,
        boto_session: Optional[boto3.Session] = None,
    ) -> None:
        self._memory_id = memory_id
        self._actor_id = actor_id
        self._region = region
        self._logger = logger
        session = boto_session or boto3.Session()
        self._client = session.client(self._SERVICE, region_name=region)

    # ── Save ──────────────────────────────────────────────────────────────────

    def save_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Persist a single conversation turn into AgentCore Memory.

        Args:
            session_id: The wizard session_id (used as memory session key).
            role:       'user' or 'assistant'.
            content:    The message text.
            metadata:   Optional dict of extra fields to store alongside.
        """
        record: dict[str, Any] = {
            "role": role,
            "content": content,
        }
        if metadata:
            record["metadata"] = metadata

        try:
            self._client.put_memory_records(
                memoryId=self._memory_id,
                actorId=self._actor_id,
                sessionId=session_id,
                memoryRecords=[
                    {
                        "content": {
                            "text": json.dumps(record, ensure_ascii=False, default=str)
                        }
                    }
                ],
            )
            self._logger.debug(  # type: ignore[attr-defined]
                "memory_saved", session_id=session_id, role=role
            )
        except ClientError as exc:
            self._logger.error(  # type: ignore[attr-defined]
                "memory_save_failed", exc=exc, session_id=session_id
            )

    # ── Load ──────────────────────────────────────────────────────────────────

    def recall_session(self, session_id: str) -> list[dict]:
        """Return all memory records for *session_id*, oldest first.

        Returns an empty list if the session does not exist or an error occurs.
        """
        try:
            paginator = self._client.get_paginator("list_memory_records")
            pages = paginator.paginate(
                memoryId=self._memory_id,
                actorId=self._actor_id,
                sessionId=session_id,
            )
            records: list[dict] = []
            for page in pages:
                for item in page.get("memoryRecords", []):
                    text = item.get("content", {}).get("text", "{}")
                    try:
                        records.append(json.loads(text))
                    except json.JSONDecodeError:
                        records.append({"raw": text})
            self._logger.info(  # type: ignore[attr-defined]
                "memory_recalled", session_id=session_id, count=len(records)
            )
            return records
        except ClientError as exc:
            self._logger.error(  # type: ignore[attr-defined]
                "memory_recall_failed", exc=exc, session_id=session_id
            )
            return []

    # ── Summarize ─────────────────────────────────────────────────────────────

    def summarize_session(self, session_id: str) -> str:
        """Return a lightweight text summary of stored conversation turns."""
        records = self.recall_session(session_id)
        if not records:
            return f"No hay registros en memoria para session_id={session_id}"

        lines: list[str] = [
            f"Memory summary – session_id={session_id}  ({len(records)} turnos)\n"
        ]
        for i, rec in enumerate(records, start=1):
            role = rec.get("role", "unknown")
            content = rec.get("content", "")[:200]
            lines.append(f"  [{i}] {role}: {content}")
        return "\n".join(lines)

    # ── Check session existence ───────────────────────────────────────────────

    def session_exists(self, session_id: str) -> bool:
        """Return True if there is at least one memory record for *session_id*."""
        records = self.recall_session(session_id)
        return len(records) > 0
