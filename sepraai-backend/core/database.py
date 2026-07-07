"""
SepraAI v2.7 — Database Connection & Utilities

Manages connection pools, SQLAlchemy sessions, and database migrations,
including raw SQL for triggers to enforce database-level immutability constraints.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import text

from core.config import settings

logger = logging.getLogger(__name__)

# Configure Async Engine with pool parameters matching v2.7 settings
engine = create_async_engine(
    str(settings.DATABASE_URL),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    echo=settings.DB_ECHO_SQL,
)

# Async Session Factory
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for safely getting a database session.
    Automatically handles rollback on exceptions and cleanup.
    """
    session = async_session_factory()
    try:
        yield session
    except Exception as e:
        logger.error("Database session encountered exception, rolling back: %s", e)
        await session.rollback()
        raise
    finally:
        await session.close()


async def run_migrations() -> None:
    """
    Runs DDL tasks that are not easily modeled in basic ORM setups,
    specifically creating the database-level BEFORE UPDATE trigger
    on the `global_context_manifests` table to enforce immutability (Patch #13).
    """
    trigger_function_ddl = """
    CREATE OR REPLACE FUNCTION check_gcm_immutability()
    RETURNS TRIGGER AS $$
    BEGIN
        -- Check if any video_part_jobs associated with this GCM have status 'rendering' or beyond.
        -- Status check corresponds to: 'rendering', 'rendered', 'completed', etc.
        -- We assume the order of enum is handled, or we check explicitly against statuses.
        IF EXISTS (
            SELECT 1 FROM video_part_jobs
            WHERE gcm_id = OLD.id
              AND status IN ('rendering', 'rendered', 'assembling', 'assembled', 'review_gate', 'completed')
        ) THEN
            -- If someone is trying to update style parameters or structural GCM details, block it.
            -- Allowed updates: None, once rendering is reached.
            RAISE EXCEPTION 'GCMImmutabilityError: GCM is locked and cannot be mutated because associated video part jobs are rendering/completed.';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

    trigger_ddl = """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'trg_gcm_immutability'
        ) THEN
            CREATE TRIGGER trg_gcm_immutability
            BEFORE UPDATE ON global_context_manifests
            FOR EACH ROW
            EXECUTE FUNCTION check_gcm_immutability();
        END IF;
    END;
    $$;
    """

    async with engine.begin() as conn:
        logger.info("Executing GCM immutability database trigger DDL...")
        # We run these as raw SQL execution on the connection
        await conn.execute(text(trigger_function_ddl))
        await conn.execute(text(trigger_ddl))
        logger.info("GCM immutability database trigger verified.")
