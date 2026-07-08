"""
SepraAI v2.7 — Configuration

All environment-driven settings with strict validation.
Follows the 12-Factor App methodology.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field, PostgresDsn, RedisDsn


class Settings(BaseSettings):
    """
    Application-wide configuration.
    All values are sourced from environment variables with sensible defaults
    for local development. Production must set explicit values.
    """

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn = Field(
        default="postgresql+asyncpg://sepraai:sepraai@127.0.0.1:5432/sepraai",
        description="Async Postgres connection string (asyncpg driver required)",
    )
    DB_POOL_SIZE: int = Field(default=20, ge=5, le=100)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=50)
    DB_POOL_RECYCLE: int = Field(
        default=300,
        description="Seconds before a pooled connection is recycled",
    )
    DB_ECHO_SQL: bool = Field(
        default=False,
        description="Echo all SQL to stdout",
    )

    # ── Redis / ARQ ──────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = Field(
        default="redis://127.0.0.1:6379/0",
        description="Redis used by ARQ for task queues",
    )
    ARQ_JOB_TIMEOUT: int = Field(
        default=600,
        description="Seconds — must be >= 3× p99 render latency",
    )
    ARQ_HEARTBEAT_INTERVAL: int = Field(
        default=15,
        description="Seconds between worker heartbeats (v2.7 Heartbeat Rule)",
    )

    # ── MinIO / S3 ────────────────────────────────────────────────────────
    MINIO_ENDPOINT: str = Field(default="localhost:9000")
    MINIO_ACCESS_KEY: str = Field(default="minioadmin")
    MINIO_SECRET_KEY: str = Field(default="minioadmin")
    MINIO_BUCKET: str = Field(default="sepraai-assets")
    MINIO_USE_SSL: bool = Field(default=False)

    # ── Backpressure (v2.5) ────────────────────────────────────────────────
    BACKPRESSURE_QUEUE_DEPTH_LIMIT: int = Field(
        default=500,
        description="429 returned when any pool queue exceeds this depth",
    )
    BACKPRESSURE_RETRY_AFTER: int = Field(
        default=30,
        description="Retry-After header value in seconds",
    )

    # ── Healing (v2.7 KEDA Rule — scale-to-zero) ─────────────────────────
    HEALING_MAX_RETRIES: int = Field(default=3, ge=1, le=10)
    HEALING_INITIAL_TEMPERATURE: float = Field(default=0.1, ge=0.0, le=1.0)
    HEALING_TEMPERATURE_STEP: float = Field(default=0.3)
    HEALING_PER_CHUNK_BUDGET_SECONDS: int = Field(
        default=300,
        description="Max wall-clock seconds spent healing a single chunk",
    )

    # ── Optimistic Lock (v2.7 Rollup Rule) ────────────────────────────────
    OPTIMISTIC_LOCK_MAX_RETRIES: int = Field(default=5, ge=1)
    OPTIMISTIC_LOCK_BASE_BACKOFF_MS: int = Field(default=50)
    OPTIMISTIC_LOCK_MAX_BACKOFF_MS: int = Field(default=800)

    # ── Chunk Limits ──────────────────────────────────────────────────────
    CHUNK_TARGET_DURATION_S: float = Field(default=30.0)
    CHUNK_HARD_CAP_DURATION_S: float = Field(default=45.0)
    CHUNK_WORD_BOUNDARY_GRACE_S: float = Field(
        default=3.0,
        description="v2.7: extend cap by up to this value to snap to word boundary",
    )

    # ── TTS (v2.7 CBR Rule) ──────────────────────────────────────────────
    TTS_OUTPUT_SAMPLE_RATE: int = Field(default=48000)
    TTS_OUTPUT_BIT_DEPTH: int = Field(default=16)

    # ── pgvector ──────────────────────────────────────────────────────────
    EMBEDDING_DIMENSIONS: int = Field(default=1536)

    model_config = {
        "env_prefix": "SEPRAAI_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


# Singleton instance
settings = Settings()
