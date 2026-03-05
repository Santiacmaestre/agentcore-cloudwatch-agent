"""session_cache.py – In-process cache for assumed-role boto3 sessions.

Credentials obtained via ``sts:AssumeRole`` expire after a configurable
duration.  This module stores them in a simple dict keyed by
``(role_arn, region)`` and refreshes automatically when the TTL has passed.

Thread safety: This implementation uses a simple dict lock and is safe
for single-threaded async code (the default usage pattern).  For true
multi-threaded use, replace with a threading.Lock.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.credentials import RefreshableCredentials


# ── Constants ────────────────────────────────────────────────────────────────

# Refresh credentials 5 minutes before they expire
_REFRESH_MARGIN_SECONDS = 300


# ── Cache entry ───────────────────────────────────────────────────────────────

@dataclass
class _CacheEntry:
    session: boto3.Session
    expires_at: float       # Unix timestamp


# ── Cache ─────────────────────────────────────────────────────────────────────

class SessionCache:
    """Lazy cache of boto3 sessions keyed by ``(role_arn, region)``."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], _CacheEntry] = {}

    def _is_valid(self, entry: _CacheEntry) -> bool:
        return time.time() < (entry.expires_at - _REFRESH_MARGIN_SECONDS)

    def get(self, role_arn: str, region: str) -> Optional[boto3.Session]:
        """Return a cached session if still valid, else None."""
        entry = self._cache.get((role_arn, region))
        if entry and self._is_valid(entry):
            return entry.session
        return None

    def put(
        self,
        role_arn: str,
        region: str,
        session: boto3.Session,
        expires_at: float,
    ) -> None:
        """Store a session in the cache."""
        self._cache[(role_arn, region)] = _CacheEntry(
            session=session, expires_at=expires_at
        )

    def invalidate(self, role_arn: str, region: str) -> None:
        """Remove a cached session."""
        self._cache.pop((role_arn, region), None)

    def clear(self) -> None:
        """Evict all cached sessions."""
        self._cache.clear()


# ── Module-level singleton ────────────────────────────────────────────────────

_DEFAULT_CACHE: Optional[SessionCache] = None


def get_default_cache() -> SessionCache:
    """Return (and lazily build) the module-level singleton SessionCache."""
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        _DEFAULT_CACHE = SessionCache()
    return _DEFAULT_CACHE
