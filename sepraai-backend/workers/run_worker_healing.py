"""
SepraAI v2.7 — Healing Worker Task

Invokes the LangGraph verification and healing state machine (Sprints 4 & 5).
Safeguards the queue by monitoring executing retries.
"""

from __future__ import annotations

import logging
import uuid
import time
from typing import Any

from orchestration.arq_broker import with_heartbeat
from agents.graph import compile_verification_graph

logger = logging.getLogger(__name__)


@with_heartbeat
async def run_healing_orchestration_task(
    ctx: dict[str, Any],
    chunk_id: uuid.UUID,
    original_code: str,
) -> dict[str, Any]:
    """
    ARQ Task coordinator orchestrating self-healing loops for a broken chunk.
    Enforces overall execution time limit boundaries.
    """
    logger.info("Healing Worker: Starting verification graph for chunk %s...", chunk_id)
    start_time = time.monotonic()

    # Compile the LangGraph verification state machine (or fallback loop)
    graph = compile_verification_graph()

    # Initialize Graph State parameters
    initial_state = {
        "chunk_id": chunk_id,
        "original_code": original_code,
        "start_time": start_time,
    }

    # Execute State Machine
    final_state = await graph.ainvoke(initial_state)

    logger.info(
        "Healing Worker: Completed orchestration for chunk %s. Status: %s, Elapsed: %.2fs",
        chunk_id,
        final_state.get("status"),
        time.monotonic() - start_time,
    )

    return {
        "chunk_id": str(chunk_id),
        "status": final_state.get("status"),
        "healed_code": final_state.get("healed_code"),
        "errors": final_state.get("prior_errors", []),
    }
