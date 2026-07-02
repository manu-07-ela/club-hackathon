# syntax=docker/dockerfile:1

# --- Build stage: resolve & install dependencies with uv ---------------------
FROM ghcr.io/astral-sh/uv:python3.14-alpine AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install only the locked dependencies first for better layer caching.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# --- Runtime stage: minimal alpine image with just the venv + app ------------
FROM python:3.14-alpine

WORKDIR /app

# Bring in the prebuilt virtual environment and the application code only.
# The build context is the `api/` folder, so the source lives at the context
# root. Copy it back under an `api/` package dir so `api.main:app` resolves.
COPY --from=builder /app/.venv /app/.venv
COPY main.py ./api/main.py
COPY middleware ./api/middleware
COPY queries ./api/queries
COPY utils ./api/utils

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
