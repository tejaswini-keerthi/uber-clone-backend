# uber-clone-backend

FastAPI backend for the Uber-clone ride-hailing system. Async-first, three-layer
architecture (API → service → repository), PostgreSQL+PostGIS, Redis, Kafka, and
WebSockets.

See the [project root README](../README.md) for full architecture, setup, and demo.

## Quick start (local)

```bash
uv sync --extra dev          # install deps into .venv
cp .env.example .env         # configure
uv run uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/health`
