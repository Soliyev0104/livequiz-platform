# syntax=docker/dockerfile:1.7
# Multi-stage build for the FastAPI backend.
#   * builder stage installs deps with uv into a virtualenv
#   * runtime stage is slim, runs as non-root `app`, ships curl for HEALTHCHECK

FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv from the official distribution.
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml ./
# uv.lock is optional during P00. If present it is honoured via --frozen,
# otherwise uv generates one inside the image.
COPY uv.loc[k] ./
RUN if [ -f uv.lock ]; then \
        uv sync --frozen --no-install-project; \
    else \
        uv sync --no-install-project; \
    fi

# ---- runtime ----
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app \
    && useradd --no-log-init -r -g app app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY . /app
RUN chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD curl -f http://localhost:8000/api/v1/ready || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
