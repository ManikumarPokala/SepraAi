"""
SepraAI v2.7 — ARQ Broker & Heartbeat Controller

Defines task queues and task functions wrapper.
Implements the Heartbeat Rule (Patch #2) where all workers run `await job.heartbeat()`
every 15 seconds to extend visibility timeouts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine
from arq import cron
from arq.jobs import Job
from arq.connections import RedisSettings, ArqRedis

from core.config import settings

logger = logging.getLogger(__name__)


# ── Heartbeat Mixin / Loop Utility (Patch #2) ─────────────────────────────

async def arq_heartbeat_monitor(job: Job, interval: int) -> None:
    """
    Background worker loop targeting the active ARQ job.
    Keeps the visibility window refreshed during heavy visual rendering.
    """
    logger.debug("Heartbeat monitor started for ARQ Job: %s", job.job_id)
    while True:
        try:
            await asyncio.sleep(interval)
            # Invoke ARQ job's native heartbeat command
            await job.heartbeat()
            logger.debug("Sent heartbeat update for job %s", job.job_id)
        except asyncio.CancelledError:
            logger.debug("Heartbeat monitor cancelled for job %s", job.job_id)
            break
        except Exception as e:
            logger.error("Failed to propagate heartbeat for job %s: %s", job.job_id, e)


def with_heartbeat(task_func: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Coroutine[Any, Any, Any]]:
    """
    Decorator to wrap async task functions executing on workers.
    Ensures a background heartbeat task is running alongside the rendering logic.
    """
    async def wrapper(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        job: Job | None = ctx.get("job")
        if not job:
            # Local run or context missing job info — bypass heartbeat monitor
            return await task_func(ctx, *args, **kwargs)

        # Launch heartbeat runner task in background
        heartbeat_task = asyncio.create_task(
            arq_heartbeat_monitor(job, settings.ARQ_HEARTBEAT_INTERVAL)
        )
        try:
            return await task_func(ctx, *args, **kwargs)
        finally:
            # Terminate and cleanup heartbeat monitoring
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    wrapper.__name__ = task_func.__name__
    return wrapper


# ── ARQ Task Definitions and Settings ────────────────────────────────────

# Standard ARQ Worker Settings Class Schema
class WorkerSettings:
    """
    Production-ready worker configuration.
    Sets Redis settings, pool schemas, and max timeouts matching setting budgets.
    """
    redis_settings = RedisSettings(
        host=str(settings.REDIS_URL.host or "localhost"),
        port=settings.REDIS_URL.port or 6379,
        database=int(settings.REDIS_URL.path.lstrip("/") or 0) if settings.REDIS_URL.path else 0,
        password=settings.REDIS_URL.password,
    )

    # All pools share the central timeout parameter representing 3× p99 latency
    job_timeout = settings.ARQ_JOB_TIMEOUT

    # List of functions mapping workers to task keys
    functions = []
