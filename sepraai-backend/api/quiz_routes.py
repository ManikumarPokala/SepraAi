"""
API Routes for the AI Quiz Generation Service.

Exposes endpoints for creating quiz generation jobs, listing jobs,
and retrieving quiz results.
"""

from __future__ import annotations

import uuid
import datetime
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.dependencies import get_db
from api.input_sanitizer import sanitize_curriculum_prompt
from core.database import async_session_factory
from core.models import QuizJob, QuizItem
from core.schemas import QuizJobCreate, QuizJobResponse
from core.quiz_pipeline import run_quiz_item_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/quiz", tags=["quiz"])


# ── Background Task Runner ────────────────────────────────────────────────

async def run_quiz_generation_job(job_id: uuid.UUID, subject: str, difficulty: str, num_items: int) -> None:
    """
    Background worker task coordinating the quiz generation pipeline.
    Runs each item through the creator -> judge -> repair loop,
    tracks individual item costs, and rolls them up to the parent job.
    """
    logger.info("Initializing background quiz generation for Job %s...", job_id)

    # 1. Update status to generating
    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = select(QuizJob).where(QuizJob.id == job_id)
                res = await session.execute(stmt)
                job = res.scalar_one_or_none()
                if not job:
                    logger.error("QuizJob %s not found during background task start.", job_id)
                    return
                job.status = "generating"
                job.updated_at = datetime.datetime.utcnow()
    except Exception as e:
        logger.error("Failed to transition QuizJob %s to generating state: %s", job_id, e)
        return

    generated_items = []
    total_cost_usd = 0.0

    try:
        for idx in range(num_items):
            # To demonstrate the self-healing capability, we trigger self-healing (flawed generation on attempt 1)
            # deliberately on the very first question (idx == 0).
            trigger_healing = (idx == 0)

            # Run the multi-agent pipeline (Creator -> Judge -> Repair -> Finalize)
            result = await run_quiz_item_pipeline(
                subject=subject,
                difficulty=difficulty,
                index=idx,
                trigger_self_healing=trigger_healing
            )

            # Construct QuizItem ORM object
            quiz_item = QuizItem(
                id=uuid.uuid4(),
                quiz_job_id=job_id,
                question=result["question"],
                choices=result["choices"],
                correct_answer=result["correct_answer"],
                explanation=result["explanation"],
                cost_usd=result["cost_usd"],
                attempts=result["attempts"]
            )
            generated_items.append(quiz_item)
            total_cost_usd += result["cost_usd"]

        # 2. Persist items and mark job as completed in a single atomic transaction
        async with async_session_factory() as session:
            async with session.begin():
                # Re-fetch parent job
                stmt = select(QuizJob).where(QuizJob.id == job_id)
                res = await session.execute(stmt)
                job = res.scalar_one_or_none()

                if job:
                    # Add all child items
                    for item in generated_items:
                        session.add(item)
                    
                    job.status = "completed"
                    job.total_cost = round(total_cost_usd, 6)
                    job.updated_at = datetime.datetime.utcnow()

        logger.info("QuizJob %s successfully completed. Total cost: $%s", job_id, round(total_cost_usd, 6))

    except Exception as e:
        logger.error("Critical error in QuizJob %s generation pipeline: %s", job_id, e)
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    stmt = select(QuizJob).where(QuizJob.id == job_id)
                    res = await session.execute(stmt)
                    job = res.scalar_one_or_none()
                    if job:
                        job.status = "failed"
                        job.updated_at = datetime.datetime.utcnow()
        except Exception as db_err:
            logger.error("Failed to mark QuizJob %s as failed: %s", job_id, db_err)


# ── Route Controllers ─────────────────────────────────────────────────────

@router.post("/generate", response_model=QuizJobResponse, status_code=status.HTTP_201_CREATED)
async def request_quiz_generation(
    payload: QuizJobCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db)
) -> Any:
    """
    Accepts quiz configuration parameters (subject, difficulty, count).
    Sanitizes inputs and schedules background quiz generation job.
    """
    try:
        sanitized_subject = sanitize_curriculum_prompt(payload.subject)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    # Create parent job
    job_id = uuid.uuid4()
    job = QuizJob(
        id=job_id,
        subject=sanitized_subject,
        difficulty=payload.difficulty,
        num_items=payload.num_items,
        status="pending",
        total_cost=0.0
    )

    async with session.begin():
        session.add(job)

    # Schedule non-blocking generation task in background thread
    background_tasks.add_task(
        run_quiz_generation_job,
        job_id,
        sanitized_subject,
        payload.difficulty,
        payload.num_items
    )

    await session.refresh(job)
    return job


@router.get("/jobs", response_model=list[QuizJobResponse])
async def list_quiz_jobs(
    session: AsyncSession = Depends(get_db)
) -> Any:
    """
    Lists all submitted quiz jobs.
    """
    stmt = select(QuizJob).options(selectinload(QuizJob.items)).order_by(QuizJob.created_at.desc())
    res = await session.execute(stmt)
    jobs = res.scalars().all()
    return jobs


@router.get("/jobs/{job_id}", response_model=QuizJobResponse)
async def get_quiz_job_details(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db)
) -> Any:
    """
    Retrieves status and results for a specific quiz job, loading generated questions.
    """
    stmt = select(QuizJob).options(selectinload(QuizJob.items)).where(QuizJob.id == job_id)
    res = await session.execute(stmt)
    job = res.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quiz job {job_id} not found."
        )
    return job
