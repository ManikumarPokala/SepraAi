"""
SepraAI v2.7 — Main FastAPI Gateway Entrypoint

Compiles the central FastAPI application:
- Loads environment settings.
- Configures Redis connections.
- Registers QueueBackpressureMiddleware to prevent service saturation (Patch #9).
- Exposes Prometheus monitoring endpoints.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI
import redis.asyncio as aioredis

from core.config import settings
from api.routes import router
from api.chemistry_routes import router as chemistry_router
from api.quiz_routes import router as quiz_router
from api.backpressure import QueueBackpressureMiddleware, get_redis_queue_depth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Scoped redis client placeholder for middleware injections
redis_client: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manages lifespan startup and shutdown tasks, such as Redis connection pools.
    """
    global redis_client
    logger.info("Initializing API Gateway startup hooks...")

    # Run database migrations and schema setup automatically
    try:
        from db_init import init_database
        await init_database()
        logger.info("Database initialized successfully at startup.")
    except Exception as e:
        logger.error("Failed to initialize database at startup: %s", e)

    # Initialize async Redis pool matching setting connections
    redis_client = aioredis.from_url(
        str(settings.REDIS_URL),
        encoding="utf-8",
        decode_responses=True,
    )
    # Register the connection instance to the app state for reference
    app.state.redis = redis_client

    yield

    logger.info("Closing API Gateway resource pools...")
    if redis_client:
        await redis_client.close()


# Compile core FastAPI application
app = FastAPI(
    title="SepraAI Gateway",
    version="2.7.0",
    description="Asynchronous Map-Reduce AI media generation platform.",
    lifespan=lifespan,
)

# ── Backpressure Middleware registration (Patch #9) ──────────────────────

# We wrap client reference dynamically or initialize after lifespan setup
# In FastAPI, we can add middleware classes using the lifespan hook
# Since middleware runs before lifespan on initial setup, we instantiate it dynamically
# using an adapter pattern or injecting the client wrapper.
# A clean pattern is passing the app state or a lazy resolver.
class LazyRedisMiddleware(QueueBackpressureMiddleware):
    def __init__(self, app: Any) -> None:
        super().__init__(app, redis_client=None)

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        # Dynamically inject the initialized connection pool from app state
        self.redis_client = request.app.state.redis
        return await super().dispatch(request, call_next)


app.add_middleware(LazyRedisMiddleware)

# Include core routes
app.include_router(router)
app.include_router(chemistry_router)
app.include_router(quiz_router)


# ── Monitoring endpoints ──────────────────────────────────────────────────

@app.get("/metrics")
async def get_system_metrics() -> dict[str, Any]:
    """
    Custom Prometheus scrape endpoint returning system gauges and health checks.
    """
    global redis_client
    queue_len = 0
    if redis_client:
        queue_len = await get_redis_queue_depth(redis_client)

    return {
        "status": "healthy",
        "arq_queue_depth": queue_len,
        "backpressure_limit": settings.BACKPRESSURE_QUEUE_DEPTH_LIMIT,
        "active_pool_configurations": [
            "cpu_manim",
            "cpu_remotion",
            "gpu_align",
            "gpu_healing"
        ]
    }
