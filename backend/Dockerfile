# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

# uv: fast, reproducible installs from pyproject.toml
COPY --from=ghcr.io/astral-sh/uv:0.2.27 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# System deps: libpq for asyncpg/psycopg, build tooling for any wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cached layer) using the lockable pyproject.
COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

# App source
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
