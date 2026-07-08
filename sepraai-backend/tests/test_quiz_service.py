"""
Test Suite for the AI Quiz Generation Service.

Verifies:
- Agent cost tracking math.
- Quality gates logic (Judge Agent).
- Self-healing repair pipeline (Creator -> Judge -> Repair -> Judge).
- Endpoint functions with mocked session states.
"""

from __future__ import annotations

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.quiz_pipeline import AgentCostTracker, JudgeAgent, run_quiz_item_pipeline
from core.models import QuizJob, QuizItem
from core.schemas import QuizJobCreate
from api.quiz_routes import (
    request_quiz_generation,
    list_quiz_jobs,
    get_quiz_job_details
)

def test_quiz_agent_cost_tracking():
    """Asserts that cost calculation matches expected token pricing."""
    tracker = AgentCostTracker("creator_repair")
    cost = tracker.calculate_cost(input_tokens=1000, output_tokens=2000)
    # Creator input rate is 0.003/1000, output rate is 0.015/1000
    # Cost = (1000 * 0.003 / 1000) + (2000 * 0.015 / 1000) = 0.003 + 0.030 = 0.033
    assert cost == 0.033


def test_judge_quality_gate_checks():
    """Asserts that JudgeAgent correctly flags invalid formats and passes valid ones."""
    judge = JudgeAgent()

    # 1. Healthy valid item
    valid_item = {
        "question": "What is 2 + 2?",
        "choices": ["3", "4", "5", "6"],
        "correct_answer": "4",
        "explanation": "Simple arithmetic."
    }
    passed, feedback, _ = judge.evaluate_item(valid_item)
    assert passed is True
    assert feedback is None

    # 2. Invalid item: too few choices (3 options)
    invalid_choices = {
        "question": "What is 2 + 2?",
        "choices": ["3", "4", "5"],
        "correct_answer": "4",
        "explanation": "Simple arithmetic."
    }
    passed, feedback, _ = judge.evaluate_item(invalid_choices)
    assert passed is False
    assert "exactly 4 options" in feedback

    # 3. Invalid item: correct answer missing from options list
    missing_answer = {
        "question": "What is 2 + 2?",
        "choices": ["3", "5", "6", "7"],
        "correct_answer": "4",
        "explanation": "Simple arithmetic."
    }
    passed, feedback, _ = judge.evaluate_item(missing_answer)
    assert passed is False
    assert "not listed in the options" in feedback


@pytest.mark.asyncio
async def test_quiz_pipeline_self_healing():
    """
    Asserts that forcing a faulty question triggers the self-healing loop:
    Creator generates flawed -> Judge rejects -> Repair patches -> Judge approves -> finalizes.
    """
    # Run the pipeline with self-healing triggered for index 0
    result = await run_quiz_item_pipeline(
        subject="secondary school chemistry",
        difficulty="beginner",
        index=0,
        trigger_self_healing=True
    )

    # Output structure must be clean and verified
    assert result["attempts"] == 2  # Shows it took exactly 2 attempts to heal (attempt 1 failed, attempt 2 healed)
    assert len(result["choices"]) == 4
    assert result["correct_answer"] == "H2O"
    assert result["cost_usd"] > 0.0


# ── Endpoint Route Direct Unit Tests ──────────────────────────────────────

@pytest.mark.asyncio
async def test_request_quiz_generation_endpoint():
    """Verifies POST /generate creates job and queues background task."""
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.begin = MagicMock()
    mock_db.refresh = AsyncMock()
    mock_background_tasks = MagicMock()

    payload = QuizJobCreate(subject="Biology", difficulty="Advanced", num_items=3)

    job = await request_quiz_generation(
        payload=payload,
        background_tasks=mock_background_tasks,
        session=mock_db
    )

    assert isinstance(job, QuizJob)
    assert job.subject == "Biology"
    assert job.status == "pending"
    assert job.total_cost == 0.0

    mock_db.add.assert_called_once_with(job)
    mock_background_tasks.add_task.assert_called_once()
    mock_db.refresh.assert_called_once_with(job)


@pytest.mark.asyncio
async def test_list_quiz_jobs_endpoint():
    """Verifies GET /jobs lists jobs from database."""
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_jobs = [
        QuizJob(id=uuid.uuid4(), subject="Physics", status="completed"),
        QuizJob(id=uuid.uuid4(), subject="Maths", status="generating")
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_jobs
    mock_db.execute.return_value = mock_result

    jobs = await list_quiz_jobs(session=mock_db)
    assert len(jobs) == 2
    assert jobs[0].subject == "Physics"
    assert jobs[1].subject == "Maths"
    mock_db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_quiz_job_details_endpoint():
    """Verifies GET /jobs/{job_id} retrieves specific job or raises 404."""
    job_id = uuid.uuid4()
    mock_job = QuizJob(id=job_id, subject="Chemistry", status="completed")

    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_job
    mock_db.execute.return_value = mock_result

    # 1. Success case
    job = await get_quiz_job_details(job_id=job_id, session=mock_db)
    assert job.id == job_id
    assert job.status == "completed"

    # 2. 404 Not Found case
    mock_result.scalar_one_or_none.return_value = None
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await get_quiz_job_details(job_id=job_id, session=mock_db)
    assert exc.value.status_code == 404
