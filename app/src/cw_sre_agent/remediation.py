"""remediation.py – Strands tool that writes remediation actions to SSM Parameter Store.

Registered as a Strands @tool so the agent can trigger remediation actions
autonomously when it detects errors in CloudWatch logs. Writes directly to SSM
without intermediate Lambda invocation.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from strands import tool


@tool
def write_to_parameter_store(
    error_type: str,
    error_category: str,
    source_log_group: str,
    summary: str,
    action: str,
    severity: str = "MEDIUM",
    parameter_name: str = "/sre-agent/actions/latest",
) -> dict[str, Any]:
    """Write a remediation action to AWS Systems Manager Parameter Store.

    Call this tool when you detect errors in CloudWatch logs and have determined
    the appropriate remediation action. This tool writes the findings and action
    directly to SSM Parameter Store at /sre-agent/actions/latest (by default).

    The tool should be called AFTER you have:
    1. Analyzed the CloudWatch logs using the query tools
    2. Identified specific error types, patterns, and severity
    3. Determined the appropriate remediation action

    **WHEN TO USE:**
    - After finding ERROR or CRITICAL level logs
    - When you have identified the root cause or error category
    - When you have determined a specific remediation action

    **WHEN NOT TO USE:**
    - If no errors or critical issues are found
    - If only INFO/DEBUG level logs are present
    - If the user explicitly asks NOT to trigger any action

    Args:
        error_type: The primary error type detected (e.g. "DatabaseConnectionError",
                    "OOMKilled", "UpstreamTimeout", "AuthenticationFailure").
        error_category: Broad category of the error; must be one of:
                        database, http, resource, auth, compute, messaging, tls.
        source_log_group: The CloudWatch Log Group where the errors were found.
        summary: A concise human-readable summary of the findings
                 (e.g. "Detected 15 DatabaseConnectionError events in /demo/app-logs
                 over the last 6 hours; connections exceeded 80% of max capacity").
        action: The remediation action to be taken (e.g. "scale_up_connections",
                "restart_service", "alert_on_call", "increase_memory_limit",
                "rotate_certificates", "enable_caching").
        severity: Severity level – one of LOW, MEDIUM, HIGH, CRITICAL.
                  Use HIGH or CRITICAL if errors are actively impacting users.
        parameter_name: The SSM Parameter Store path to write to.
                        Defaults to "/sre-agent/actions/latest".
                        Parameter will be created or overwritten.

    Returns:
        A dict with status, parameter name, and timestamp:
        {
            "status": "success",
            "parameter_name": "/sre-agent/actions/latest",
            "timestamp": "2026-03-08T14:30:00Z"
        }

    Raises:
        Exception: If SSM Parameter Store write fails (e.g., IAM permissions issue).
    """
    region = os.environ.get("AWS_REGION", "us-west-2")
    now = datetime.now(timezone.utc).isoformat()

    value = json.dumps({
        "timestamp": now,
        "error_type": error_type,
        "error_category": error_category,
        "source_log_group": source_log_group,
        "summary": summary,
        "action": action,
        "severity": severity,
    })

    ssm = boto3.client("ssm", region_name=region)
    ssm.put_parameter(
        Name=parameter_name,
        Value=value,
        Type="String",
        Overwrite=True,
        Description=f"SRE Agent remediation – {error_type} – {now}",
    )

    return {
        "status": "success",
        "parameter_name": parameter_name,
        "timestamp": now,
    }
