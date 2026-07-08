"""
API Routes for the AI Chemistry Video Request Service.

Exposes endpoints for posting concepts, checking status, listing jobs,
and downloading completed video artifacts.
"""

from __future__ import annotations

import os
import uuid
import datetime
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.input_sanitizer import sanitize_curriculum_prompt
from core.database import async_session_factory
from core.models import ChemistryVideoJob
from core.schemas import ChemistryVideoJobCreate, ChemistryVideoJobResponse
from core.chemistry_generator import generate_chemistry_video

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chemistry", tags=["chemistry"])

# ── Background Task Runner ────────────────────────────────────────────────

async def run_generation_job(job_id: uuid.UUID, concept: str) -> None:
    """
    Background worker task to coordinate video generation.
    Handles retries, updates status, and logs errors cleanly.
    """
    max_retries = 3
    retry_count = 0

    # 1. Update status to processing
    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = select(ChemistryVideoJob).where(ChemistryVideoJob.id == job_id)
                res = await session.execute(stmt)
                job = res.scalar_one_or_none()
                if not job:
                    logger.error("Job %s not found in background task startup.", job_id)
                    return
                job.status = "processing"
                job.updated_at = datetime.datetime.utcnow()
    except Exception as e:
        logger.error("Failed to transition job %s to processing state: %s", job_id, e)
        return

    # Determine artifact output path inside the workspace
    artifacts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../artifacts/videos"))
    os.makedirs(artifacts_dir, exist_ok=True)
    output_video_path = os.path.join(artifacts_dir, f"{job_id}.mp4")

    # Retry loop for visual rendering robust to transient glitches
    while retry_count < max_retries:
        try:
            logger.info("Generating chemistry video for job %s (attempt %s/%s)...", job_id, retry_count + 1, max_retries)
            
            # Execute synchronous FFmpeg rendering in an async threadpool executor
            import asyncio
            await asyncio.to_thread(generate_chemistry_video, concept, output_video_path)

            # 2. Update status to done
            async with async_session_factory() as session:
                async with session.begin():
                    stmt = select(ChemistryVideoJob).where(ChemistryVideoJob.id == job_id)
                    res = await session.execute(stmt)
                    job = res.scalar_one_or_none()
                    if job:
                        job.status = "done"
                        job.video_path = output_video_path
                        job.retry_count = retry_count
                        job.error_message = None
                        job.updated_at = datetime.datetime.utcnow()

            logger.info("Job %s finished successfully. Artifact stored at %s", job_id, output_video_path)
            return

        except Exception as e:
            logger.error("Attempt %s failed for job %s: %s", retry_count + 1, job_id, e)
            retry_count += 1
            if retry_count >= max_retries:
                # Update status to failed after final attempt
                try:
                    async with async_session_factory() as session:
                        async with session.begin():
                            stmt = select(ChemistryVideoJob).where(ChemistryVideoJob.id == job_id)
                            res = await session.execute(stmt)
                            job = res.scalar_one_or_none()
                            if job:
                                job.status = "failed"
                                job.retry_count = retry_count
                                job.error_message = str(e)
                                job.updated_at = datetime.datetime.utcnow()
                except Exception as db_err:
                    logger.error("Failed to commit failed status for job %s: %s", job_id, db_err)

                logger.error("Job %s marked as failed after %s attempts.", job_id, max_retries)
                return

            # Short wait before retry
            import asyncio
            await asyncio.sleep(1.0)


# ── Route Controllers ─────────────────────────────────────────────────────

@router.post("/videos", response_model=ChemistryVideoJobResponse, status_code=status.HTTP_201_CREATED)
async def request_chemistry_video(
    payload: ChemistryVideoJobCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db)
) -> Any:
    """
    Submits a chemistry concept query. Sanitizes input and schedules async rendering.
    """
    try:
        sanitized_concept = sanitize_curriculum_prompt(payload.concept)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    # 1. Create queued job record
    job_id = uuid.uuid4()
    job = ChemistryVideoJob(
        id=job_id,
        concept=sanitized_concept,
        status="queued",
        retry_count=0
    )

    async with session.begin():
        session.add(job)

    # 2. Schedule background video generation task
    background_tasks.add_task(run_generation_job, job_id, sanitized_concept)

    # Return refreshed job response
    await session.refresh(job)
    return job


@router.get("/videos", response_model=list[ChemistryVideoJobResponse])
async def list_chemistry_videos(
    session: AsyncSession = Depends(get_db)
) -> Any:
    """
    Lists all submitted chemistry concept video jobs, sorted by creation date.
    """
    stmt = select(ChemistryVideoJob).order_by(ChemistryVideoJob.created_at.desc())
    res = await session.execute(stmt)
    jobs = res.scalars().all()
    return jobs


@router.get("/videos/{job_id}", response_model=ChemistryVideoJobResponse)
async def get_chemistry_video_status(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db)
) -> Any:
    """
    Retrieves status of a specific chemistry video generation job.
    """
    stmt = select(ChemistryVideoJob).where(ChemistryVideoJob.id == job_id)
    res = await session.execute(stmt)
    job = res.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chemistry video job {job_id} not found."
        )
    return job


@router.get("/videos/{job_id}/file")
async def retrieve_completed_video_file(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db)
) -> Any:
    """
    Retrieves and streams the completed MP4 video file artifact.
    """
    stmt = select(ChemistryVideoJob).where(ChemistryVideoJob.id == job_id)
    res = await session.execute(stmt)
    job = res.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chemistry video job {job_id} not found."
        )

    if job.status != "done":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot download video: job status is currently '{job.status}'."
        )

    if not job.video_path or not os.path.exists(job.video_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Completed video file is missing on the filesystem."
        )

    return FileResponse(
        path=job.video_path,
        media_type="video/mp4",
        filename=f"chemistry_{job_id}.mp4"
    )
