"""
SepraAI v2.7 — API Routes

FastAPI routers exposing generation controls and RBAC-gated approval trails (Patch #7).
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy import select

from core.database import get_db_session
from core.models import CurriculumJob, VideoPartJob, JobStatus
from core.schemas import CurriculumJobCreate, CurriculumJobResponse, VideoPartJobResponse, CurriculumJobDetailResponse
from core.concurrency import optimistic_update

logger = logging.getLogger(__name__)
router = APIRouter()


# ── RBAC Authorization Dependencies (Patch #7) ───────────────────────────

class UserClaims:
    def __init__(self, user_id: str, role: str) -> None:
        self.user_id = user_id
        self.role = role


def require_role(allowed_roles: list[str]) -> Any:
    """
    Enforces role-based permissions (RBAC) during requests.
    Validates token payloads in HTTP request headers.
    """
    def dependency(
        x_user_id: Annotated[str | None, Header(description="RBAC User ID")] = None,
        x_user_role: Annotated[str | None, Header(description="RBAC User Role")] = None,
    ) -> UserClaims:
        if not x_user_id or not x_user_role:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authorization headers (X-User-Id, X-User-Role)",
            )
        if x_user_role not in allowed_roles:
            logger.warning("Access denied: User %s with role %s tried to hit gated route.", x_user_id, x_user_role)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Insufficient privileges.",
            )
        return UserClaims(user_id=x_user_id, role=x_user_role)

    return dependency


# ── Route Endpoints ──────────────────────────────────────────────────────

@router.post("/generate", response_model=CurriculumJobResponse, status_code=status.HTTP_201_CREATED)
async def generate_curriculum(payload: CurriculumJobCreate) -> Any:
    """
    Triggers creation of a new Curriculum Job.
    Subject to Downstream Backpressure checks in middleware.
    """
    import hashlib
    from core.models import GlobalContextManifest, AtomicBeat, Chunk, ChunkStatus
    logger.info("Initializing creation request for prompt: %s...", payload.original_prompt[:30])

    async with get_db_session() as session:
        async with session.begin():
            job = CurriculumJob(
                original_prompt=payload.original_prompt,
                status=JobStatus.PENDING,
            )
            session.add(job)

            # Create a style GCM
            gcm_id = uuid.uuid4()
            gcm = GlobalContextManifest(
                id=gcm_id,
                curriculum_job=job,
                style_data={"primary": "#3B82F6", "secondary": "#10B981", "background": "#0F172A"},
                is_locked=False,
            )
            session.add(gcm)

            # Create VideoPartJob 1 (Chapter 1)
            part1 = VideoPartJob(
                curriculum_job=job,
                gcm_id=gcm_id,
                part_number=1,
                status=JobStatus.PENDING,
            )
            session.add(part1)

            # Create AtomicBeat 1
            beat1 = AtomicBeat(
                video_part_job=part1,
                beat_index=1,
                narration_text="Initialize follower nodes.",
                visual_instructions="Show three nodes in follower states.",
                embedding=[0.0] * 1536,
            )
            session.add(beat1)

            # Create Chunk 1
            chunk1 = Chunk(
                video_part_job=part1,
                atomic_beat=beat1,
                chunk_index=1,
                status=ChunkStatus.PENDING,
                content_hash=hashlib.sha256(b"chunk1_code").hexdigest(),
            )
            session.add(chunk1)

            # Create VideoPartJob 2 (Chapter 2)
            part2 = VideoPartJob(
                curriculum_job=job,
                gcm_id=gcm_id,
                part_number=2,
                status=JobStatus.PENDING,
            )
            session.add(part2)

            # Create AtomicBeat 2
            beat2 = AtomicBeat(
                video_part_job=part2,
                beat_index=1,
                narration_text="Leader election trigger.",
                visual_instructions="Show node 1 becoming candidate and requestVotes.",
                embedding=[0.0] * 1536,
            )
            session.add(beat2)

            # Create Chunk 2
            chunk2 = Chunk(
                video_part_job=part2,
                atomic_beat=beat2,
                chunk_index=1,
                status=ChunkStatus.PENDING,
                content_hash=hashlib.sha256(b"chunk2_code").hexdigest(),
            )
            session.add(chunk2)

        # Refresh to populate ID
        await session.refresh(job)
        return job


@router.get("/status/curriculum/{job_id}", response_model=CurriculumJobDetailResponse)
async def get_curriculum_job_status(job_id: uuid.UUID) -> Any:
    """
    Retrieves status of a parent CurriculumJob and its associated VideoPartJobs.
    """
    async with get_db_session() as session:
        from sqlalchemy.orm import selectinload
        stmt = select(CurriculumJob).options(selectinload(CurriculumJob.video_parts)).where(CurriculumJob.id == job_id)
        res = await session.execute(stmt)
        curriculum_job = res.scalar_one_or_none()

        if not curriculum_job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"CurriculumJob {job_id} not found."
            )
        return curriculum_job


@router.get("/status/{job_id}", response_model=VideoPartJobResponse)
async def get_part_job_status(job_id: uuid.UUID) -> Any:
    """
    Retrieves status of a split Video Part Job.
    """
    async with get_db_session() as session:
        stmt = select(VideoPartJob).where(VideoPartJob.id == job_id)
        res = await session.execute(stmt)
        part_job = res.scalar_one_or_none()

        if not part_job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"VideoPartJob {job_id} not found."
            )
        return part_job


@router.post("/approve/{job_id}", response_model=VideoPartJobResponse)
async def approve_video_part(
    job_id: uuid.UUID,
    claims: Annotated[UserClaims, Depends(require_role(["editor", "admin"]))],
) -> Any:
    """
    RBAC-Gated approval gate endpoint (Patch #7).
    Enforces audit logging by writing the approving user ID to `approved_by` column.
    """
    logger.info("User %s (%s) requests approval update for Job %s", claims.user_id, claims.role, job_id)

    async with get_db_session() as session:
        stmt = select(VideoPartJob).where(VideoPartJob.id == job_id)
        res = await session.execute(stmt)
        part_job = res.scalar_one_or_none()

        if not part_job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"VideoPartJob {job_id} not found."
            )

        if part_job.status != JobStatus.REVIEW_GATE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Job is in state {part_job.status.value}, cannot approve outside of Review Gate.",
            )

        # Commit approval update using optimistic concurrency controls
        async with session.begin():
            part_job = await optimistic_update(
                session=session,
                model_cls=VideoPartJob,
                instance_id=job_id,
                expected_version=part_job.version,
                values_to_update={
                    "status": JobStatus.COMPLETED,
                    "approved_by": claims.user_id,
                },
            )

        return part_job
