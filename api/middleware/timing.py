from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request

logger = logging.getLogger("api.timing")


def register_timing_middleware(app: FastAPI) -> None:
    """Attach a middleware that records and logs per-request latency."""

    @app.middleware("http")
    async def add_timing(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
        query = f"?{request.url.query}" if request.url.query else ""
        logger.info(
            "%s %s%s -> %s in %.2f ms",
            request.method,
            request.url.path,
            query,
            response.status_code,
            elapsed_ms,
        )
        return response
