# ============================================================
# Agent Platform - Multi-stage Production Build
# ============================================================
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# --- Builder stage ---
FROM base AS builder

RUN pip install --upgrade pip hatchling
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --prefix=/install .

# --- Runtime stage ---
FROM base AS runtime

# Security: non-root user for agent execution
RUN groupadd --gid 1000 agent && \
    useradd --uid 1000 --gid agent --shell /bin/bash --create-home agent

COPY --from=builder /install /usr/local
COPY src/ src/
COPY eval/ eval/

# Sandbox workspace for agent file operations
RUN mkdir -p /workspace && chown agent:agent /workspace

USER agent
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "agent_platform.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
