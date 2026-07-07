"""
SepraAI v2.7 — Backpressure Middleware

Implements Gateway Backpressure (Patch #9):
- Connects to task queues to monitor lengths.
- Returns 429 Too Many Requests with a Retry-After header if queue depth exceeds limit.
"""

from __future__ import annotations

import logging
from typing import Any
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from core.config import settings

logger = logging.getLogger(__name__)


# Mock connection helper for checking Redis key size
async def get_redis_queue_depth(redis_client: Any) -> int:
    """
    Retrieves the length of the ARQ queues in Redis.
    In ARQ, jobs are typically stored in a sorted set (default key: 'arq:queue').
    """
    try:
        # zcard retrieves the cardinality (length) of the sorted set
        queue_len = await redis_client.zcard("arq:queue")
        return int(queue_len)
    except Exception as e:
        logger.error("Failed to query queue length from Redis: %s", e)
        # Safe default to avoid locking gateway on Redis transient errors
        return 0


class QueueBackpressureMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware enforcing structural backpressure (Patch #9).
    Monitors queue depth before letting `/generate` requests propagate.
    """

    def __init__(self, app: Any, redis_client: Any) -> None:
        super().__init__(app)
        self.redis_client = redis_client

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Only apply backpressure checks to the generation initiation routes
        if request.url.path == "/generate" and request.method == "POST":
            queue_depth = await get_redis_queue_depth(self.redis_client)
            limit = settings.BACKPRESSURE_QUEUE_DEPTH_LIMIT
            if queue_depth >= limit:
                logger.warning(
                    "Backpressure triggered! Queue depth is at %d (Limit: %d). "
                    "Rejecting request with HTTP 429.",
                    queue_depth,
                    limit,
                )

                # Return HTTP 429 Too Many Requests with Retry-After header
                headers = {"Retry-After": str(settings.BACKPRESSURE_RETRY_AFTER)}
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers=headers,
                    content={
                        "error": "QueueOverflowError",
                        "message": "Downstream queues are heavily saturated. Please try again later.",
                        "current_queue_depth": queue_depth,
                        "limit": limit,
                    },
                )

        return await call_next(request)
