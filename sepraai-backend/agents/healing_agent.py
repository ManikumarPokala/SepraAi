"""
SepraAI v2.7 — Agent Healing Loop

Implements the Escalation Rule (Patch #11) and healing queue protection (Patch #10):
- Tracks elapsed wall-clock seconds to respect the 300s time budget.
- Escalates temperature (0.1 -> 0.4 -> 0.7) and appends prior-error context.
- Triggers Layout Override dynamically.
- Triggers re-running the studio time-scaler mapping upon successful heal (Patch #7).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db_session
from core.models import Chunk, ChunkStatus, HealingAttempt, DeadLetterQueue, DLQReason
from core.schemas import HealingRequest
from core.concurrency import optimistic_update, enqueue_to_dlq, aggregate_job_rollup

logger = logging.getLogger(__name__)


# Mock function representing vLLM call
async def call_healing_vllm(prompt: str, temperature: float) -> str:
    """
    Simulates calling vLLM / Llama-3 warm instance.
    Returns simulated healed visual code with modified dimensions/corrections.
    """
    logger.info("Calling vLLM. Temp: %.1f, Prompt length: %d", temperature, len(prompt))
    return (
        "# Healed Manim Visual Script\n"
        "from manim import *\n"
        "class SceneChunk(Scene):\n"
        "    def construct(self):\n"
        "        # Visual adjustments applied (grid constraint fixed)\n"
        "        text = Text('Healed Scene Content', font_size=32)\n"
        "        self.play(Write(text))\n"
        "        self.wait(2.0)\n"
    )


# Stub for Studio Editor time-scaler re-run (Patch #7)
async def rerun_studio_editor_time_scaler(chunk_id: uuid.UUID, healed_code: str) -> float:
    """
    Re-evaluates animation graph of the healed code.
    Returns the new visual duration in seconds.
    """
    logger.info("Re-running Studio Editor time-scaler for Chunk %s", chunk_id)
    # Parse code, check self.play/self.wait calls, and scale them to match audio duration
    return 30.0  # target duration


async def execute_healing_cycle(
    chunk_id: uuid.UUID,
    original_code: str,
    prior_errors: list[str],
    start_time_stamp: float,
) -> dict[str, Any]:
    """
    Executes a single step in the self-healing loop.
    Enforces temperature settings, context mutation, and timing safety budgets.
    """
    # 1. Enforce time-budget protection (Patch #10)
    elapsed_seconds = time.monotonic() - start_time_stamp
    if elapsed_seconds > settings.HEALING_PER_CHUNK_BUDGET_SECONDS:
        error_msg = (
            f"Healing safety budget exceeded: Spent {elapsed_seconds:.1f}s healing chunk {chunk_id} "
            f"exceeding cap of {settings.HEALING_PER_CHUNK_BUDGET_SECONDS}s. DLQ escalated."
        )
        logger.error(error_msg)
        async with get_db_session() as session:
            await enqueue_to_dlq(
                session=session,
                reason=DLQReason.HEALING_EXHAUSTED,
                error_message=error_msg,
                chunk_id=chunk_id,
            )
            # Mark chunk as permanently failed
            stmt = select(Chunk).where(Chunk.id == chunk_id)
            res = await session.execute(stmt)
            chunk = res.scalar_one_or_none()
            if chunk:
                async with session.begin():
                    await optimistic_update(
                        session=session,
                        model_cls=Chunk,
                        instance_id=chunk_id,
                        expected_version=chunk.version,
                        values_to_update={"status": ChunkStatus.FAILED},
                    )
                    await aggregate_job_rollup(session, chunk.video_part_job_id)
        return {"status": "failed", "reason": "budget_exceeded"}

    async with get_db_session() as session:
        # Determine attempt number by counting existing entries
        count_stmt = select(func.count(HealingAttempt.id)).where(HealingAttempt.chunk_id == chunk_id)
        count_res = await session.execute(count_stmt)
        attempt_count = count_res.scalar_one()
        attempt_number = attempt_count + 1

        # Check chunk model details
        chunk_stmt = select(Chunk).where(Chunk.id == chunk_id)
        chunk_res = await session.execute(chunk_stmt)
        chunk = chunk_res.scalar_one_or_none()
        if not chunk:
            raise ValueError(f"Chunk {chunk_id} not found.")

        current_version = chunk.version

    # 2. Implements the Escalation Rule parameters (Patch #11)
    if attempt_number == 1:
        temp = 0.1
        prompt_instruction = (
            f"Fix the following visual code based on these error logs:\n"
            f"Error Logs: {' '.join(prior_errors)}\n"
            f"Code:\n{original_code}"
        )
        layout_override = False
    elif attempt_number == 2:
        temp = 0.4
        # Add negative prompting: "Do NOT repeat prior fix"
        prompt_instruction = (
            f"Fix the following visual code. Do NOT repeat the previous incorrect fix logic.\n"
            f"Errors identified in previous attempt: {' '.join(prior_errors)}\n"
            f"Code:\n{original_code}"
        )
        layout_override = False
    else:  # Attempt 3+
        temp = 0.7
        # Trigger Layout Override parameters to break deadlocks
        layout_override = True
        prompt_instruction = (
            f"CRITICAL: Triggering layout override to prevent constraint deadlock.\n"
            f"Divide visual elements or simplify elements layout to fit within grid boundaries.\n"
            f"Prior error logs: {' '.join(prior_errors)}\n"
            f"Code:\n{original_code}"
        )

    # If retries exceeded settings.HEALING_MAX_RETRIES, DLQ immediately
    if attempt_number > settings.HEALING_MAX_RETRIES:
        error_msg = f"Healing retry limit ({settings.HEALING_MAX_RETRIES}) exhausted for chunk {chunk_id}."
        logger.error(error_msg)
        async with get_db_session() as session:
            await enqueue_to_dlq(
                session=session,
                reason=DLQReason.HEALING_EXHAUSTED,
                error_message=error_msg,
                chunk_id=chunk_id,
            )
            async with session.begin():
                await optimistic_update(
                    session=session,
                    model_cls=Chunk,
                    instance_id=chunk_id,
                    expected_version=current_version,
                    values_to_update={"status": ChunkStatus.FAILED},
                )
                await aggregate_job_rollup(session, chunk.video_part_job_id)
        return {"status": "failed", "reason": "retries_exhausted"}

    # Transition chunk status to HEALING
    async with get_db_session() as session:
        async with session.begin():
            chunk = await optimistic_update(
                session=session,
                model_cls=Chunk,
                instance_id=chunk_id,
                expected_version=current_version,
                values_to_update={"status": ChunkStatus.HEALING},
            )
            current_version = chunk.version

    # Invoke LLM (vLLM pool)
    try:
        healed_code = await call_healing_vllm(prompt_instruction, temperature=temp)

        # Recheck elapsed seconds before logging attempt and database commits
        elapsed_seconds = time.monotonic() - start_time_stamp
        if elapsed_seconds > settings.HEALING_PER_CHUNK_BUDGET_SECONDS:
            raise TimeoutError("Healing budget timed out inside vLLM callback.")

        # Log this attempt in database
        async with get_db_session() as session:
            async with session.begin():
                attempt_log = HealingAttempt(
                    chunk_id=chunk_id,
                    attempt_number=attempt_number,
                    temperature=temp,
                    prior_error_context=" ".join(prior_errors),
                    generated_code=healed_code,
                )
                session.add(attempt_log)

            # 3. Re-run Studio Editor time-scaler to match timelines (Patch #7)
            new_duration = await rerun_studio_editor_time_scaler(chunk_id, healed_code)
            logger.info("Time scale re-evaluated. Healed visual duration scaled to: %.2fs", new_duration)

            # Re-queue chunk for rendering: set status to PENDING
            async with session.begin():
                await optimistic_update(
                    session=session,
                    model_cls=Chunk,
                    instance_id=chunk_id,
                    expected_version=current_version,
                    values_to_update={"status": ChunkStatus.PENDING},
                )
                await aggregate_job_rollup(session, chunk.video_part_job_id)

        return {
            "status": "success",
            "healed_code": healed_code,
            "attempt": attempt_number,
            "layout_override": layout_override,
            "duration": new_duration,
        }

    except Exception as e:
        logger.error("Error in healing loop execution step: %s", e)
        async with get_db_session() as session:
            await enqueue_to_dlq(
                session=session,
                reason=DLQReason.CRITICAL_ERROR,
                error_message=f"Healing exception during execution: {e}",
                chunk_id=chunk_id,
            )
        return {"status": "error", "message": str(e)}
