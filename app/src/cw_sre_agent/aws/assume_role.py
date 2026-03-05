"""assume_role.py – AssumeRoleSessionFactory for cross-account access.

Given an account_id + role_arn + region, produces a boto3 session whose
credentials are obtained via ``sts:AssumeRole``.

Usage::

    factory = AssumeRoleSessionFactory(logger=my_logger)
    session = factory.get_session(
        account_id="123456789012",
        role_arn="arn:aws:iam::123456789012:role/SRE-ReadOnly",
        region="us-east-1",
    )
    cw_client = session.client("logs")

Role ARN format validation::

    arn:aws:iam::<account_id>:role/<role_name>
"""

from __future__ import annotations

import re
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from cw_sre_agent.aws.session_cache import SessionCache, get_default_cache

# ── ARN validation ────────────────────────────────────────────────────────────

_ROLE_ARN_PATTERN = re.compile(
    r"^arn:aws(?:-cn|-us-gov)?:iam::\d{12}:role/[\w+=,.@/-]{1,512}$"
)

_ACCOUNT_ID_PATTERN = re.compile(r"^\d{12}$")


def validate_role_arn(role_arn: str) -> None:
    """Raise ``ValueError`` if *role_arn* does not match the expected format."""
    if not _ROLE_ARN_PATTERN.match(role_arn):
        raise ValueError(
            f"Invalid role ARN: '{role_arn}'.\n"
            "Expected format: arn:aws:iam::<12-digit-account-id>:role/<role-name>"
        )


def validate_account_id(account_id: str) -> None:
    """Raise ``ValueError`` if *account_id* is not a 12-digit string."""
    if not _ACCOUNT_ID_PATTERN.match(account_id):
        raise ValueError(
            f"Invalid account ID: '{account_id}'.  Must be exactly 12 digits."
        )


# ── Factory ───────────────────────────────────────────────────────────────────

class AssumeRoleSessionFactory:
    """Creates and caches boto3 sessions for cross-account roles.

    Args:
        logger:          An :class:`~cw_sre_agent.logging.AgentLogger` instance
                         (or any object with ``info`` / ``error`` methods).
        session_duration_seconds: How long the assumed-role credentials last.
                         Default is 1 hour (the minimum for most roles).
        cache:           A :class:`~cw_sre_agent.aws.session_cache.SessionCache`.
                         Defaults to the module-level singleton.
        base_session:    The source boto3 session to call STS from (defaults to
                         the ambient EC2/ECS role when running on AgentCore).
    """

    def __init__(
        self,
        logger: object,
        session_duration_seconds: int = 3600,
        cache: Optional[SessionCache] = None,
        base_session: Optional[boto3.Session] = None,
    ) -> None:
        self._logger = logger
        self._duration = session_duration_seconds
        self._cache = cache or get_default_cache()
        self._base_session = base_session or boto3.Session()

    # ── Public API ────────────────────────────────────────────────────────────

    def get_session(
        self,
        account_id: str,
        role_arn: str,
        region: str,
        role_session_name: str = "cw-sre-agent",
    ) -> boto3.Session:
        """Return a boto3 session with credentials for *role_arn* in *region*.

        Results are cached for ``session_duration_seconds - 5 min``.

        Raises ``ValueError`` if the role ARN or account ID is invalid.
        Raises ``botocore.exceptions.ClientError`` on STS API failures.
        """
        validate_account_id(account_id)
        validate_role_arn(role_arn)

        # Check cache first
        cached = self._cache.get(role_arn, region)
        if cached:
            return cached

        # Assume role
        sts = self._base_session.client("sts", region_name=region)
        try:
            resp = sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName=role_session_name,
                DurationSeconds=self._duration,
            )
        except ClientError as exc:
            self._logger.error(  # type: ignore[attr-defined]
                "assume_role_failed",
                exc=exc,
                role_arn=role_arn,
                account_id=account_id,
                region=region,
            )
            raise

        creds = resp["Credentials"]
        expiration = creds["Expiration"]
        # expiration is a datetime; convert to unix timestamp
        expires_at = expiration.timestamp()

        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )

        self._cache.put(role_arn, region, session, expires_at)

        self._logger.info(  # type: ignore[attr-defined]
            "assumed_role",
            account_id=account_id,
            role_arn=role_arn,
            region=region,
            expires_at=expiration.isoformat(),
        )
        return session

    def get_client(
        self,
        service_name: str,
        account_id: str,
        role_arn: str,
        region: str,
    ) -> object:
        """Convenience shortcut: return a boto3 client for *service_name*.

        Equivalent to ``get_session(...).client(service_name)``.
        """
        session = self.get_session(account_id=account_id, role_arn=role_arn, region=region)
        return session.client(service_name, region_name=region)

    def build_env_vars(
        self,
        account_id: str,
        role_arn: str,
        region: str,
    ) -> dict[str, str]:
        """Return a dict of ``AWS_*`` env vars suitable for subprocess injection.

        Use this when you need to pass assumed-role credentials to a child
        process (e.g., an MCP server subprocess).
        """
        session = self.get_session(account_id=account_id, role_arn=role_arn, region=region)
        creds = session.get_credentials().get_frozen_credentials()
        return {
            "AWS_ACCESS_KEY_ID":     creds.access_key,
            "AWS_SECRET_ACCESS_KEY": creds.secret_key,
            "AWS_SESSION_TOKEN":     creds.token or "",
            "AWS_DEFAULT_REGION":    region,
        }
