"""
SepraAI v2.7 — Concurrency & Locking Safety Utilities

Implements the Concurrency Rules defined in the v2.7 Implementation Directives:
- The Transaction Rule: Single async transaction block for status and asset cache updates.
- Optimistic Lock policy: Retries with jittered backoff, DLQ escalation on exhaustion.
- The Rollup Rule support: Aggregation helper to update video part jobs without lock contention.
- ChunkReaper daemon task to reap zombie chunks.
"""

from __future__ import annotations

import asyncio
import random
import logging
import uuid
import datetime
from typing import Type, TypeVar, Any, Callable

from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.models import (
    Base,
    Chunk,
    ChunkStatus,
    VideoPartJob,
    JobStatus,
    AssetCache,
    DeadLetterQueue,
    DLQReason,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Base)


# ── Optimistic Locking Utility (Patch #12) ───────────────────────────────

async def optimistic_update(
    session: AsyncSession,
    model_cls: Type[T],
    instance_id: uuid.UUID,
    expected_version: int,
    values_to_update: dict[str, Any],
) -> T:
    """
    Performs an update on an ORM model utilizing optimistic locking.
    Retries up to config.OPTIMISTIC_LOCK_MAX_RETRIES times with jittered exponential backoff.
    Escalates to DLQ on failure.
    """
    max_retries = settings.OPTIMISTIC_LOCK_MAX_RETRIES
    base_backoff = settings.OPTIMISTIC_LOCK_BASE_BACKOFF_MS
    max_backoff = settings.OPTIMISTIC_LOCK_MAX_BACKOFF_MS

    for attempt in range(max_retries):
        # Prepare updates
        # Auto-increment the version column
        stmt = (
            update(model_cls)
            .where(
                and_(
                    model_cls.id == instance_id,
                    model_cls.version == expected_version,
                )
            )
            .values(**values_to_update, version=model_cls.version + 1)
            .returning(model_cls)
        )

        result = await session.execute(stmt)
        updated_row = result.scalar_one_or_none()

        if updated_row is not None:
            # Commit immediately as part of caller's transaction flow or within our control
            # But the caller should dictate commit. To be safe, we flush here.
            await session.flush()
            return updated_row

        # Conflict detected (no row matched with the expected version)
        if attempt == max_retries - 1:
            error_msg = (
                f"Optimistic lock conflict: {model_cls.__name__} (ID: {instance_id}) "
                f"expected version {expected_version} was modified by another transaction."
            )
            logger.error(error_msg)
            # Escalation to DLQ
            await enqueue_to_dlq(
                session=session,
                reason=DLQReason.LOCK_CONTENTION,
                error_message=error_msg,
                chunk_id=instance_id if model_cls is Chunk else None,
                video_part_job_id=instance_id if model_cls is VideoPartJob else None,
            )
            raise RuntimeError(error_msg)

        # Calculate jittered exponential backoff
        # backoff = min(max_backoff, base_backoff * (2 ** attempt))
        # jitter = random.uniform(0, backoff)
        temp_backoff = min(max_backoff, base_backoff * (2**attempt))
        sleep_ms = random.uniform(50, temp_backoff)
        logger.warning(
            "Optimistic lock collision for %s %s (expected version %d). Retrying in %.2fms...",
            model_cls.__name__,
            instance_id,
            expected_version,
            sleep_ms,
        )
        await asyncio.sleep(sleep_ms / 1000.0)

        # Refresh expected version for next loop by querying latest row
        latest_stmt = select(model_cls.version).where(model_cls.id == instance_id)
        latest_res = await session.execute(latest_stmt)
        latest_version = latest_res.scalar_one_or_none()
        if latest_version is None:
            raise ValueError(f"Instance {instance_id} of {model_cls.__name__} not found during retry.")
        expected_version = latest_version

    raise RuntimeError("Optimistic lock retry loop exited unexpectedly")


# ── The Transaction Rule (Patch #1) ──────────────────────────────────────

async def atomic_chunk_commit(
    session: AsyncSession,
    chunk_id: uuid.UUID,
    content_hash: str,
    storage_path: str,
    video_path: str,
    audio_path: str,
    version: int,
) -> None:
    """
    Implements 'The Transaction Rule':
    Wraps asset cache insertion and chunk status update in a single transaction block.
    Guarantees no orphaned files or intermediate state commits.
    """
    async with session.begin():
        # 1. Insert Cache Entry
        cache_entry = AssetCache(
            content_hash=content_hash,
            chunk_id=chunk_id,
            storage_path=storage_path,
        )
        session.add(cache_entry)

        # 2. Update Chunk Status to rendered and set paths using Optimistic Lock helper
        # Optimistic locking operates inside the transaction context
        await optimistic_update(
            session=session,
            model_cls=Chunk,
            instance_id=chunk_id,
            expected_version=version,
            values_to_update={
                "status": ChunkStatus.RENDERED,
                "video_path": video_path,
                "audio_path": audio_path,
            },
        )
        # Session auto-commits when exiting the transaction block (async with session.begin())


# ── Rollup Rule Aggregation Task (Patch #12) ──────────────────────────────

async def aggregate_job_rollup(session: AsyncSession, video_part_job_id: uuid.UUID) -> None:
    """
    Implements 'The Rollup Rule':
    Workers never write to the parent job status. This utility aggregates chunk statuses
    separately to evaluate if the job is completed or requires transitions.
    Executed by a serialized coordinator process, removing contention.
    """
    # 1. Query count of chunks for this video part job grouped by status
    stmt = (
        select(Chunk.status, func.count(Chunk.id))
        .where(Chunk.video_part_job_id == video_part_job_id)
        .group_by(Chunk.status)
    )
    result = await session.execute(stmt)
    status_counts = dict(result.all())

    # Get total chunk count
    total_chunks = sum(status_counts.values())
    if total_chunks == 0:
        return

    rendered_count = status_counts.get(ChunkStatus.RENDERED, 0)
    failed_count = status_counts.get(ChunkStatus.FAILED, 0)

    # Load video part job to get version for optimistic lock
    job_stmt = select(VideoPartJob).where(VideoPartJob.id == video_part_job_id)
    job_res = await session.execute(job_stmt)
    job = job_res.scalar_one_or_none()
    if not job:
        return

    # Decide next status
    target_status = job.status
    if rendered_count == total_chunks:
        target_status = JobStatus.ASSEMBLED
    elif failed_count > 0 or (rendered_count + failed_count == total_chunks and failed_count > 0):
        target_status = JobStatus.FAILED
    elif status_counts.get(ChunkStatus.RENDERING, 0) > 0 or status_counts.get(ChunkStatus.HEALING, 0) > 0:
        target_status = JobStatus.RENDERING

    if target_status != job.status:
        logger.info(
            "Rollup updating VideoPartJob %s status from %s -> %s",
            video_part_job_id,
            job.status.value,
            target_status.value,
        )
        await optimistic_update(
            session=session,
            model_cls=VideoPartJob,
            instance_id=video_part_job_id,
            expected_version=job.version,
            values_to_update={"status": target_status},
        )


# ── DLQ Escalation ────────────────────────────────────────────────────────

async def enqueue_to_dlq(
    session: AsyncSession,
    reason: DLQReason,
    error_message: str,
    chunk_id: uuid.UUID | None = None,
    video_part_job_id: uuid.UUID | None = None,
) -> None:
    """Utility to safely insert failed requests into DLQ."""
    dlq_entry = DeadLetterQueue(
        chunk_id=chunk_id,
        video_part_job_id=video_part_job_id,
        reason=reason,
        error_message=error_message,
    )
    session.add(dlq_entry)
    await session.commit()


# ── ChunkReaper Daemon (Patch #1) ────────────────────────────────────────

async def run_chunk_reaper(session_factory: Callable[[], AsyncSession]) -> None:
    """
    Background loop querying for chunks stuck in `rendering` longer than double
    their maximum expected render time, and moves them to DLQ or mark for requeue.
    """
    max_expected_render_time = settings.ARQ_JOB_TIMEOUT // 3  # Based on timeout scale
    zombie_threshold = datetime.datetime.utcnow() - datetime.timedelta(
        seconds=max_expected_render_time * 2
    )

    logger.info("Starting ChunkReaper background loop...")
    while True:
        try:
            await asyncio.sleep(60.0)  # Check every minute
            async with session_factory() as session:
                async with session.begin():
                    # Query chunks stuck in rendering before threshold
                    stmt = select(Chunk).where(
                        and_(
                            Chunk.status == ChunkStatus.RENDERING,
                            Chunk.updated_at < zombie_threshold,
                        )
                    )
                    res = await session.execute(stmt)
                    stuck_chunks = res.scalars().all()

                    for chunk in stuck_chunks:
                        logger.warning(
                            "ChunkReaper detected zombie chunk %s stuck in RENDERING since %s.",
                            chunk.id,
                            chunk.updated_at,
                        )

                        # Enqueue to DLQ
                        dlq_entry = DeadLetterQueue(
                            chunk_id=chunk.id,
                            video_part_job_id=chunk.video_part_job_id,
                            reason=DLQReason.CRITICAL_ERROR,
                            error_message=(
                                f"Reaper: Chunk stuck in RENDERING state since {chunk.updated_at}. "
                                f"No completion received within visibility window."
                            ),
                        )
                        session.add(dlq_entry)

                        # Transition chunk status to FAILED to allow recovery or final DLQ handling
                        chunk.status = ChunkStatus.FAILED
                        session.add(chunk)

                # Post-transaction aggregates status rollup to notify parent
                async with session.begin():
                    for chunk in stuck_chunks:
                        await aggregate_job_rollup(session, chunk.video_part_job_id)

        except asyncio.CancelledError:
            logger.info("ChunkReaper cancelled. Exiting loop.")
            break
        except Exception as e:
            logger.error("ChunkReaper error: %s", e)
