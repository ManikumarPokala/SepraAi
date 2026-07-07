"""
SepraAI v2.7 — Database Schema Initializer

Bootstraps the PostgreSQL database schema:
1. Generates all mapped tables using SQLAlchemy metadata.
2. Invokes run_migrations() DDL to create the GCM BEFORE UPDATE triggers (Patch #13).
"""

import asyncio
import logging

from core.database import engine, run_migrations
from core.models import Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_database() -> None:
    logger.info("Initializing database metadata...")
    # Drop/create tables (for testing, in production migrations are managed via Alembic)
    async with engine.begin() as conn:
        logger.info("Creating all table schemas...")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Schema creation completed.")

    # Apply database triggers (Patch #13 Immutability trigger)
    await run_migrations()
    logger.info("Database bootstrap successfully completed.")


if __name__ == "__main__":
    asyncio.run(init_database())
