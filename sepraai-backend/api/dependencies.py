"""
SepraAI v2.7 — API Dependencies

Shared injectables for FastAPI endpoints, managing DB sessions,
authentication states, and metadata validation.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import async_session_factory

logger = logging.getLogger(__name__)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency yielding a scoped async database session.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception as e:
            logger.error("DB Dependency exception. Rolling back transaction: %s", e)
            await session.rollback()
            raise
        finally:
            await session.close()
