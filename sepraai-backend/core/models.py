"""
SepraAI v2.7 — Database Models & ORM Schema

Defines the complete SQLAlchemy mapping for the autonomous media platform.
Includes strict database-level constraints, index mappings, pgvector integration,
and ORM-level triggers to enforce safety protocols (e.g., GCM immutability).
"""

from __future__ import annotations

import enum
import uuid
import datetime
from typing import Any

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    Enum as SQLEnum,
    Index,
    Numeric,
    BigInteger,
    event,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column

# Robust pgvector integration fallback
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    import json
    from sqlalchemy.types import TypeDecorator

    # Fallback representation of Vector for environments where pgvector is not installed
    class Vector(TypeDecorator):  # type: ignore
        impl = Text
        cache_ok = True

        def __init__(self, dimensions: int | None = None):
            self.dimensions = dimensions
            super().__init__()

        def process_bind_param(self, value: Any, dialect: Any) -> Any:
            if value is not None:
                return json.dumps(value)
            return value

        def process_result_value(self, value: Any, dialect: Any) -> Any:
            if value is not None:
                return json.loads(value)
            return value


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


# ── Enums ─────────────────────────────────────────────────────────────────

class JobStatus(str, enum.Enum):
    PENDING = "pending"
    GROUNDING = "grounding"
    GROUNDED = "grounded"
    TTS_ALIGNING = "tts_aligning"
    SPLITTING = "splitting"
    SPLIT = "split"
    RENDERING = "rendering"
    ASSEMBLING = "assembling"
    ASSEMBLED = "assembled"
    REVIEW_GATE = "review_gate"
    COMPLETED = "completed"
    FAILED = "failed"


class ChunkStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFYING = "verifying"
    RENDERING = "rendering"
    HEALING = "healing"
    RENDERED = "rendered"
    FAILED = "failed"


class RendererType(str, enum.Enum):
    MANIM = "manim"
    REMOTION = "remotion"


class WorkerPool(str, enum.Enum):
    CPU_MANIM = "cpu_manim"
    CPU_REMOTION = "cpu_remotion"
    GPU_ALIGN = "gpu_align"
    GPU_HEALING = "gpu_healing"


class DLQReason(str, enum.Enum):
    HEALING_EXHAUSTED = "healing_exhausted"
    LOCK_CONTENTION = "lock_contention"
    SANDBOX_VIOLATION = "sandbox_violation"
    CRITICAL_ERROR = "critical_error"


# ── ORM Models ────────────────────────────────────────────────────────────

class CurriculumJob(Base):
    """
    Top-level curriculum job representing the entire video curation request.
    """
    __tablename__ = "curriculum_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    original_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SQLEnum(JobStatus, name="job_status_enum"),
        default=JobStatus.PENDING,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    # Relationships
    video_parts: Mapped[list[VideoPartJob]] = relationship(
        "VideoPartJob", back_populates="curriculum_job", cascade="all, delete-orphan"
    )
    gcm: Mapped[GlobalContextManifest] = relationship(
        "GlobalContextManifest", back_populates="curriculum_job", uselist=False
    )


class GlobalContextManifest(Base):
    """
    Global Context Manifest (GCM) ensuring stylistic consistency across curriculum chapters.
    Enforces strict immutability criteria at the ORM layer (Patch #13).
    """
    __tablename__ = "global_context_manifests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    curriculum_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    style_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    # Relationships
    curriculum_job: Mapped[CurriculumJob] = relationship(
        "CurriculumJob", back_populates="gcm"
    )


class VideoPartJob(Base):
    """
    Map-Reduce partitions of the parent CurriculumJob (10-20 mins split into chapters).
    """
    __tablename__ = "video_part_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    curriculum_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_jobs.id", ondelete="CASCADE"), nullable=False
    )
    gcm_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("global_context_manifests.id"), nullable=False
    )
    part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SQLEnum(JobStatus, name="job_status_enum"),
        default=JobStatus.PENDING,
        nullable=False,
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True, description="RBAC user ID who approved this part"
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    # Relationships
    curriculum_job: Mapped[CurriculumJob] = relationship(
        "CurriculumJob", back_populates="video_parts"
    )
    atomic_beats: Mapped[list[AtomicBeat]] = relationship(
        "AtomicBeat", back_populates="video_part_job", cascade="all, delete-orphan"
    )
    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk", back_populates="video_part_job", cascade="all, delete-orphan"
    )
    cost_attributions: Mapped[list[CostAttribution]] = relationship(
        "CostAttribution", back_populates="video_part_job", cascade="all, delete-orphan"
    )


class AtomicBeat(Base):
    """
    Granular, fact-checked sentences that construct the chapter narrative.
    Contains semantic text embeddings for grounding checks.
    """
    __tablename__ = "atomic_beats"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    video_part_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("video_part_jobs.id", ondelete="CASCADE"), nullable=False
    )
    beat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    narration_text: Mapped[str] = mapped_column(Text, nullable=False)
    visual_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    # Relationships
    video_part_job: Mapped[VideoPartJob] = relationship(
        "VideoPartJob", back_populates="atomic_beats"
    )
    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk", back_populates="atomic_beat"
    )


class Chunk(Base):
    """
    Individual render-unit representing target ~30s chunks.
    Maintains link to original atomic_beats for verification tracing (Patch #2).
    """
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    video_part_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("video_part_jobs.id", ondelete="CASCADE"), nullable=False
    )
    atomic_beat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("atomic_beats.id", ondelete="RESTRICT"),
        nullable=False,
        description="Traceability back to grounded script sentence (Patch #2)",
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[ChunkStatus] = mapped_column(
        SQLEnum(ChunkStatus, name="chunk_status_enum"),
        default=ChunkStatus.PENDING,
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        description="Deterministic hash of inputs for idempotency checks",
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    # Relationships
    video_part_job: Mapped[VideoPartJob] = relationship(
        "VideoPartJob", back_populates="chunks"
    )
    atomic_beat: Mapped[AtomicBeat] = relationship(
        "AtomicBeat", back_populates="chunks"
    )
    scene_checkpoint: Mapped[SceneCheckpoint] = relationship(
        "SceneCheckpoint", back_populates="chunk", uselist=False, cascade="all, delete-orphan"
    )
    healing_attempts: Mapped[list[HealingAttempt]] = relationship(
        "HealingAttempt", back_populates="chunk", cascade="all, delete-orphan"
    )


# Indexes for Chunk Lookups
Index("idx_chunks_atomic_beat_id", Chunk.atomic_beat_id)
Index("idx_chunks_video_part_job_status", Chunk.video_part_job_id, Chunk.status)
Index("idx_chunks_content_hash", Chunk.content_hash)


class SceneCheckpoint(Base):
    """
    Stateless snapshot schema containing visual elements.
    Acts as rehydration boundaries.
    """
    __tablename__ = "scene_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    renderer_type: Mapped[RendererType] = mapped_column(
        SQLEnum(RendererType, name="renderer_type_enum"), nullable=False
    )
    objects_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    # Relationships
    chunk: Mapped[Chunk] = relationship("Chunk", back_populates="scene_checkpoint")


class AssetCache(Base):
    """
    Maintains mapping of content hashes to stored asset blobs for render reuse.
    Satisfies v2.7 Idempotency contract.
    """
    __tablename__ = "asset_cache"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )


class HealingAttempt(Base):
    """
    Tracks iterative self-healing cycles of failing chunks (Patch #11).
    """
    __tablename__ = "healing_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    prior_error_context: Mapped[str] = mapped_column(Text, nullable=False)
    generated_code: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    # Relationships
    chunk: Mapped[Chunk] = relationship("Chunk", back_populates="healing_attempts")


class DeadLetterQueue(Base):
    """
    Stores logs and traces for broken nodes and tasks that exhausted all retry policies.
    """
    __tablename__ = "dead_letter_queue"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )
    video_part_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("video_part_jobs.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[DLQReason] = mapped_column(
        SQLEnum(DLQReason, name="dlq_reason_enum"), nullable=False
    )
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )


class CostAttribution(Base):
    """
    Tracks micro-level and macro-level execution expenses by specific worker pool (Patch #6).
    """
    __tablename__ = "cost_attributions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    video_part_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("video_part_jobs.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )
    pool: Mapped[WorkerPool] = mapped_column(
        SQLEnum(WorkerPool, name="worker_pool_enum"), nullable=False
    )
    compute_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    network_egress_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    # Relationships
    video_part_job: Mapped[VideoPartJob] = relationship(
        "VideoPartJob", back_populates="cost_attributions"
    )


# Indexing for rolling up costs by job and pool efficiently
Index("idx_cost_attr_rollup", CostAttribution.video_part_job_id, CostAttribution.pool)


# ── ORM Listeners ─────────────────────────────────────────────────────────

@event.listens_for(GlobalContextManifest, "before_update")
def enforce_gcm_orm_immutability(mapper: Any, connection: Any, target: GlobalContextManifest) -> None:
    """
    Double-layer enforcement of GCM immutability at the ORM/Application boundary (Patch #13).
    Complements the PostgreSQL BEFORE UPDATE trigger constraint.
    """
    # Check if this GCM was marked as locked
    if target.is_locked:
        raise ValueError(
            "GCMImmutabilityError: GCM is locked at ORM layer and cannot be mutated."
        )
