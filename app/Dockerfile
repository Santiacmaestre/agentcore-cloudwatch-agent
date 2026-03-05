# ──────────────────────────────────────────────────────────────
# Builder stage: install dependencies with uv
# ──────────────────────────────────────────────────────────────
FROM --platform=linux/arm64 python:3.12-slim AS builder

# Install uv
RUN pip install --no-cache-dir uv==0.4.18

WORKDIR /app

# Copy everything hatchling needs to build the package and resolve deps.
# pyproject.toml + README.md + src/ must all be present before uv runs,
# because hatchling validates readme existence and builds from src/ in one step.
COPY pyproject.toml README.md ./
COPY src/ src/

# Create venv and install the package + all runtime dependencies in one shot.
# Non-editable install embeds the wheel into the venv so it survives the
# COPY into the runtime stage without any path-based .pth indirection.
RUN uv venv .venv && \
    uv pip install --python .venv/bin/python .

# ──────────────────────────────────────────────────────────────
# Runtime stage: lean image
# ──────────────────────────────────────────────────────────────
FROM --platform=linux/arm64 python:3.12-slim AS runtime

# Non-root user for security
RUN groupadd --gid 10001 sre && \
    useradd  --uid 10001 --gid sre --no-create-home sre

WORKDIR /app

# Copy the virtualenv from builder.
# Non-editable install embeds all package code inside the venv, so
# /app/src does not need to be copied separately.
COPY --from=builder /app/.venv /app/.venv

# Make venv binaries the default Python
ENV PATH="/app/.venv/bin:$PATH"

# AgentCore sends HTTP POST requests to the container.
# uvicorn serves the FastAPI app on port 8080 (AgentCore default).
EXPOSE 8080
CMD ["uvicorn", "cw_sre_agent.server:app", "--host", "0.0.0.0", "--port", "8080"]
