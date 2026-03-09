"""log_watcher.py – Lambda triggered by CloudWatch Logs subscription filter.

Filters log events for ERROR or CRITICAL level messages, writes a summary
to SSM Parameter Store, and invokes the AgentCore runtime endpoint so the
SRE agent can investigate and trigger remediation automatically.

Expected event payload (from CloudWatch Logs subscription filter):
{
    "messageType": "DATA_MESSAGE",
    "owner": "123456789012",
    "logGroup": "/demo/app-logs",
    "logStream": "app-instance-1",
    "subscriptionFilters": ["log-watcher"],
    "logEvents": [
        {
            "id": "...",
            "timestamp": 1234567890000,
            "message": "{\"timestamp\": \"...\", \"level\": \"ERROR\", \"...\"}"
        }
    ]
}
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler triggered by CloudWatch Logs subscription filter.

    Filters for ERROR/CRITICAL logs and writes a summary to SSM Parameter Store.
    The SRE agent monitors this parameter and investigates when it changes.

    Args:
        event: CloudWatch Logs event containing log data
        context: Lambda context

    Returns:
        Response dict with processing status
    """
    try:
        # Decode and decompress the CloudWatch Logs payload
        log_data = json.loads(
            gzip.decompress(base64.b64decode(event["awslogs"]["data"]))
        )

        log_group = log_data.get("logGroup", "unknown")
        log_events = log_data.get("logEvents", [])
        region = os.environ.get("AWS_REGION", "us-west-2")

        logger.info(f"Processing {len(log_events)} events from {log_group}")

        # Filter for ERROR and CRITICAL logs
        error_events = []
        error_types = set()

        for log_event in log_events:
            message = log_event.get("message", "")

            # Try to parse as JSON; fall back to string match
            try:
                parsed = json.loads(message)
                level = parsed.get("level", "").upper()
                error_type = parsed.get("error_type", parsed.get("type", "UnknownError"))
            except (json.JSONDecodeError, AttributeError):
                # String-based level detection (fallback)
                level = ""
                error_type = "UnknownError"
                if "ERROR" in message or "CRITICAL" in message:
                    level = "ERROR" if "ERROR" in message else "CRITICAL"

            if level in ("ERROR", "CRITICAL"):
                error_events.append(log_event)
                error_types.add(error_type)

        # If no errors found, skip processing
        if not error_events:
            logger.info("No ERROR or CRITICAL logs found")
            return {"statusCode": 200, "body": "No errors detected"}

        logger.info(
            f"Found {len(error_events)} error events with types: {', '.join(error_types)}"
        )

        # Write error summary to SSM Parameter Store for audit trail
        timestamp = datetime.now(timezone.utc).isoformat()
        summary_data = {
            "timestamp": timestamp,
            "error_count": len(error_events),
            "error_types": sorted(list(error_types)),
            "source_log_group": log_group,
            "message": (
                f"Detected {len(error_events)} errors in {log_group}. "
                f"Error types: {', '.join(sorted(error_types))}. "
                f"Agent should investigate and take remediation action."
            ),
        }

        ssm = boto3.client("ssm", region_name=region)
        ssm.put_parameter(
            Name="/sre-agent/error-detected",
            Value=json.dumps(summary_data),
            Type="String",
            Overwrite=True,
            Description=f"Error detected in {log_group} at {timestamp}",
        )

        logger.info("Wrote error summary to SSM Parameter Store")

        # Invoke the AgentCore runtime endpoint to analyse and remediate
        runtime_arn = os.environ.get("AGENTCORE_RUNTIME_ARN", "")
        if not runtime_arn:
            logger.warning("AGENTCORE_RUNTIME_ARN not set – skipping agent invocation")
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": f"Error summary written for {log_group} (agent not invoked)",
                    "error_count": len(error_events),
                }),
            }

        prompt = (
            f"Errors detected in {log_group} in {region}. "
            f"Error types: {', '.join(sorted(error_types))}. "
            f"Analyse the log group for the last 1 hour and trigger remediation."
        )
        session_id = str(uuid.uuid4())
        payload = json.dumps({"inputText": prompt, "sessionId": session_id})

        agentcore = boto3.client("bedrock-agentcore", region_name=region)
        agent_response = agentcore.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            runtimeSessionId=session_id,
            payload=payload.encode("utf-8"),
            contentType="application/json",
            accept="application/json",
        )

        # Read the response body
        raw_body = (
            agent_response.get("response")
            or agent_response.get("body")
            or agent_response.get("responseStream")
        )
        response_text = ""
        if raw_body and hasattr(raw_body, "read"):
            response_text = raw_body.read().decode("utf-8", errors="replace")
        elif raw_body:
            response_text = str(raw_body)

        logger.info(f"Agent response (truncated): {response_text[:500]}")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": f"Agent invoked for {log_group}",
                "error_count": len(error_events),
                "error_types": list(error_types),
                "session_id": session_id,
            }),
        }

    except Exception as e:
        logger.exception(f"Error processing CloudWatch Logs event: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
