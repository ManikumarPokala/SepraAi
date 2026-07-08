"""
SepraAI v2.7 — Database Schema Initializer

Bootstraps the PostgreSQL database schema:
1. Generates all mapped tables using SQLAlchemy metadata.
2. Invokes run_migrations() DDL to create the GCM BEFORE UPDATE triggers (Patch #13).
"""
import sys
import os
# Auto-inject paths for database init when run directly
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), "../.venv/lib/python3.14/site-packages")))

import asyncio
import logging

from core.database import engine, run_migrations
from core.models import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_database() -> None:
    logger.info("Initializing database metadata...")
    # Drop/create tables (for testing, in production migrations are managed via Alembic)
    from sqlalchemy import text
    async with engine.begin() as conn:
        logger.info("Enabling pgvector extension...")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        logger.info("Creating all table schemas...")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Schema creation completed.")

    # Apply database triggers (Patch #13 Immutability trigger)
    await run_migrations()
    logger.info("Database bootstrap successfully completed.")


if __name__ == "__main__":
    asyncio.run(init_database())
