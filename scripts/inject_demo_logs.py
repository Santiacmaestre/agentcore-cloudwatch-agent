#!/usr/bin/env python3
"""inject_demo_logs.py – Populate a CloudWatch Log Group with realistic demo logs.

Generates a mix of normal operational logs and random errors across several
categories so the SRE agent has something interesting to analyse.

Usage:
    python scripts/inject_demo_logs.py --log-group /demo/app-logs --region us-west-2
    python scripts/inject_demo_logs.py --log-group /demo/app-logs --region us-west-2 --count 200
"""

from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import boto3

# ── Error templates ──────────────────────────────────────────────────────────

ERROR_TEMPLATES = [
    # Database errors
    {
        "level": "ERROR",
        "service": "order-service",
        "message": "DatabaseConnectionError: Connection pool exhausted – max_connections=50 reached",
        "error_type": "DatabaseConnectionError",
        "category": "database",
    },
    {
        "level": "ERROR",
        "service": "user-service",
        "message": "QueryTimeoutError: SELECT on users table exceeded 30s deadline",
        "error_type": "QueryTimeoutError",
        "category": "database",
    },
    {
        "level": "ERROR",
        "service": "inventory-service",
        "message": "DeadlockDetected: Transaction rolled back after deadlock on inventory.stock table",
        "error_type": "DeadlockDetected",
        "category": "database",
    },
    # HTTP / API errors
    {
        "level": "ERROR",
        "service": "api-gateway",
        "message": "UpstreamTimeout: POST /api/v2/checkout timed out after 10000ms (upstream: order-service)",
        "error_type": "UpstreamTimeout",
        "category": "http",
    },
    {
        "level": "ERROR",
        "service": "api-gateway",
        "message": "HTTP 503 Service Unavailable: /api/v2/payments – circuit breaker OPEN",
        "error_type": "CircuitBreakerOpen",
        "category": "http",
    },
    {
        "level": "ERROR",
        "service": "payment-service",
        "message": "HTTP 502 Bad Gateway from payment provider https://payments.example.com/charge",
        "error_type": "BadGateway",
        "category": "http",
    },
    # Memory / resource errors
    {
        "level": "CRITICAL",
        "service": "recommendation-engine",
        "message": "OutOfMemoryError: Container killed – RSS exceeded 2048Mi limit",
        "error_type": "OOMKilled",
        "category": "resource",
    },
    {
        "level": "ERROR",
        "service": "search-indexer",
        "message": "DiskPressure: /data volume at 95% capacity – eviction threshold breached",
        "error_type": "DiskPressure",
        "category": "resource",
    },
    # Authentication errors
    {
        "level": "ERROR",
        "service": "auth-service",
        "message": "TokenExpiredError: JWT token for user_id=u-83921 expired 12 minutes ago",
        "error_type": "TokenExpired",
        "category": "auth",
    },
    {
        "level": "WARN",
        "service": "auth-service",
        "message": "RateLimitExceeded: IP 192.168.1.42 exceeded 100 req/min on /login endpoint",
        "error_type": "RateLimitExceeded",
        "category": "auth",
    },
    # Lambda / compute errors
    {
        "level": "ERROR",
        "service": "data-pipeline",
        "message": "Lambda invocation failed: Function data-transform timed out after 900s",
        "error_type": "LambdaTimeout",
        "category": "compute",
    },
    {
        "level": "ERROR",
        "service": "notification-service",
        "message": "SQS SendMessage failed: Queue notification-queue.fifo is full (max=10000)",
        "error_type": "QueueFull",
        "category": "messaging",
    },
    # SSL/TLS errors
    {
        "level": "ERROR",
        "service": "api-gateway",
        "message": "TLSHandshakeError: certificate for *.internal.example.com expires in 2 days",
        "error_type": "CertExpiring",
        "category": "tls",
    },
]

# Normal operational log templates
NORMAL_TEMPLATES = [
    {"level": "INFO", "service": "order-service", "message": "Order {order_id} placed successfully – total=${ amount:.2f}"},
    {"level": "INFO", "service": "user-service", "message": "User {user_id} logged in from {ip}"},
    {"level": "INFO", "service": "payment-service", "message": "Payment {payment_id} processed – status=APPROVED"},
    {"level": "INFO", "service": "inventory-service", "message": "Stock updated for SKU {sku}: qty={qty}"},
    {"level": "INFO", "service": "api-gateway", "message": "GET /api/v2/products – 200 OK – {latency}ms"},
    {"level": "INFO", "service": "api-gateway", "message": "POST /api/v2/orders – 201 Created – {latency}ms"},
    {"level": "DEBUG", "service": "search-indexer", "message": "Indexed {doc_count} documents in {latency}ms"},
    {"level": "INFO", "service": "notification-service", "message": "Email sent to {email} – template=order_confirmation"},
    {"level": "INFO", "service": "recommendation-engine", "message": "Generated {rec_count} recommendations for user {user_id} in {latency}ms"},
    {"level": "INFO", "service": "auth-service", "message": "Token refreshed for user {user_id} – new TTL=3600s"},
    {"level": "INFO", "service": "data-pipeline", "message": "Batch {batch_id} processed: {record_count} records in {latency}ms"},
    {"level": "DEBUG", "service": "order-service", "message": "Cache HIT for product catalog – key=catalog_v3"},
    {"level": "INFO", "service": "api-gateway", "message": "Health check passed – all 6 upstreams healthy"},
]


def _random_ip() -> str:
    return f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"


def _make_normal_log(ts: datetime) -> dict:
    tmpl = random.choice(NORMAL_TEMPLATES)
    msg = tmpl["message"].format(
        order_id=f"ORD-{random.randint(100000,999999)}",
        user_id=f"u-{random.randint(10000,99999)}",
        payment_id=f"PAY-{uuid.uuid4().hex[:8]}",
        sku=f"SKU-{random.randint(1000,9999)}",
        qty=random.randint(1, 500),
        ip=_random_ip(),
        latency=random.randint(2, 450),
        doc_count=random.randint(50, 5000),
        email=f"user{random.randint(1,999)}@example.com",
        rec_count=random.randint(5, 30),
        batch_id=f"B-{random.randint(1000,9999)}",
        record_count=random.randint(100, 50000),
        amount=random.uniform(9.99, 499.99),
    )
    return {
        "timestamp": ts.isoformat(),
        "level": tmpl["level"],
        "service": tmpl["service"],
        "message": msg,
        "request_id": str(uuid.uuid4()),
    }


def _make_error_log(ts: datetime) -> dict:
    tmpl = random.choice(ERROR_TEMPLATES)
    return {
        "timestamp": ts.isoformat(),
        "level": tmpl["level"],
        "service": tmpl["service"],
        "message": tmpl["message"],
        "error_type": tmpl["error_type"],
        "category": tmpl["category"],
        "request_id": str(uuid.uuid4()),
        "trace_id": f"1-{uuid.uuid4().hex[:8]}-{uuid.uuid4().hex[:24]}",
    }


def inject_logs(
    log_group: str,
    region: str,
    total_count: int = 150,
    error_ratio: float = 0.20,
    hours_back: int = 6,
) -> None:
    """Generate and push demo logs to CloudWatch."""
    client = boto3.client("logs", region_name=region)

    # Ensure log group exists
    try:
        client.create_log_group(logGroupName=log_group)
        print(f"✅ Created log group: {log_group}")
    except client.exceptions.ResourceAlreadyExistsException:
        print(f"ℹ️  Log group already exists: {log_group}")

    # Create a log stream
    stream_name = f"demo-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    client.create_log_stream(logGroupName=log_group, logStreamName=stream_name)
    print(f"✅ Created log stream: {stream_name}")

    # Generate events
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours_back)
    events = []

    error_count = int(total_count * error_ratio)
    normal_count = total_count - error_count

    for _ in range(normal_count):
        ts = start + timedelta(seconds=random.randint(0, hours_back * 3600))
        events.append(_make_normal_log(ts))

    for _ in range(error_count):
        ts = start + timedelta(seconds=random.randint(0, hours_back * 3600))
        events.append(_make_error_log(ts))

    # Sort chronologically
    events.sort(key=lambda e: e["timestamp"])

    # Push in batches of 25 (CloudWatch limit is 10,000 per call, but keep it small)
    batch_size = 25
    total_pushed = 0

    for i in range(0, len(events), batch_size):
        batch = events[i : i + batch_size]
        log_events = [
            {
                "timestamp": int(
                    datetime.fromisoformat(e["timestamp"]).timestamp() * 1000
                ),
                "message": json.dumps(e),
            }
            for e in batch
        ]

        client.put_log_events(
            logGroupName=log_group,
            logStreamName=stream_name,
            logEvents=log_events,
        )
        total_pushed += len(batch)
        print(f"  📝 Pushed {total_pushed}/{len(events)} events...", end="\r")
        time.sleep(0.2)  # avoid throttling

    print(f"\n✅ Injected {len(events)} log events ({error_count} errors, {normal_count} normal)")
    print(f"   Log group: {log_group}")
    print(f"   Stream:    {stream_name}")
    print(f"   Region:    {region}")
    print(f"   Window:    last {hours_back}h")


def main():
    parser = argparse.ArgumentParser(description="Inject demo logs into CloudWatch")
    parser.add_argument("--log-group", required=True, help="CloudWatch Log Group name")
    parser.add_argument("--region", default="us-west-2", help="AWS region")
    parser.add_argument("--count", type=int, default=150, help="Total number of log events")
    parser.add_argument("--error-ratio", type=float, default=0.20, help="Fraction of logs that are errors (0.0-1.0)")
    parser.add_argument("--hours-back", type=int, default=6, help="How many hours back to spread logs across")
    args = parser.parse_args()

    inject_logs(
        log_group=args.log_group,
        region=args.region,
        total_count=args.count,
        error_ratio=args.error_ratio,
        hours_back=args.hours_back,
    )


if __name__ == "__main__":
    main()
