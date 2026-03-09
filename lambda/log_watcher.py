"""log_watcher.py – Lambda triggered by CloudWatch Logs subscription filter.

Filters log events for ERROR or CRITICAL level messages and invokes the
AgentCore runtime to analyze and remediate.

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
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler triggered by CloudWatch Logs subscription filter.

    Args:
        event: CloudWatch Logs event containing log data
        context: Lambda context

    Returns:
        Response dict with invocation status
    """
    try:
        # Decode and decompress the CloudWatch Logs payload
        log_data = json.loads(
            gzip.decompress(base64.b64decode(event["awslogs"]["data"]))
        )

        log_group = log_data.get("logGroup", "unknown")
        log_events = log_data.get("logEvents", [])

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

        # If no errors found, skip invocation (save cost)
        if not error_events:
            logger.info("No ERROR or CRITICAL logs found – skipping invocation")
            return {"statusCode": 200, "body": "No errors detected"}

        logger.info(
            f"Found {len(error_events)} error events with types: {', '.join(error_types)}"
        )

        # Invoke AgentCore runtime with error summary
        prompt = (
            f"Se detectaron {len(error_events)} errores en el log group {log_group}.\n"
            f"Tipos detectados: {', '.join(sorted(error_types))}.\n"
            f"Investiga el log group completo en los últimos 24 horas y toma acción de remediación "
            f"escribiendo a SSM Parameter Store en /sre-agent/actions/latest."
        )

        response = invoke_agentcore(prompt, log_group, context)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": f"Invoked AgentCore for {log_group}",
                "error_count": len(error_events),
                "error_types": list(error_types),
                "invocation_response": response,
            }),
        }

    except Exception as e:
        logger.exception(f"Error processing CloudWatch Logs event: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }


def invoke_agentcore(prompt: str, log_group: str, context: Any) -> dict[str, Any]:
    """Invoke the AgentCore runtime via bedrock-agentcore-runtime API.

    Args:
        prompt: The analysis prompt for the agent
        log_group: The log group being analyzed
        context: Lambda context (for session ID)

    Returns:
        Response from the AgentCore invocation
    """
    runtime_arn = os.environ.get("AGENTCORE_RUNTIME_ARN")
    region = os.environ.get("AWS_REGION", "us-west-2")

    if not runtime_arn:
        raise ValueError("AGENTCORE_RUNTIME_ARN environment variable not set")

    # Extract runtime ID from ARN (format: arn:aws:bedrock-agentcore:region:account:agent-runtime/id)
    runtime_id = runtime_arn.split("/")[-1]

    logger.info(f"Invoking AgentCore runtime: {runtime_id}")

    # Use bedrock-agentcore-runtime to invoke
    client = boto3.client("bedrock-agentcore-runtime", region_name=region)

    try:
        response = client.invoke_agent_runtime(
            agentRuntimeId=runtime_id,
            sessionId=f"log-watcher-{context.aws_request_id}",
            inputText=prompt,
        )

        # Collect response text from stream
        response_text = ""
        if "body" in response:
            for chunk in response["body"]:
                if "chunk" in chunk:
                    response_text += chunk["chunk"].get("bytes", "").decode("utf-8")

        logger.info(f"AgentCore invocation completed. Response length: {len(response_text)}")

        return {
            "status": "success",
            "runtime_id": runtime_id,
            "response_preview": response_text[:500],  # First 500 chars
        }

    except Exception as e:
        logger.error(f"AgentCore invocation failed: {e}")
        raise
