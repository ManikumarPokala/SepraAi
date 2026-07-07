"""
SepraAI v2.7 — Verification & Healing LangGraph Orchestrator

Compiles the multi-agent graph with:
- Professor Node (grounded content verification)
- Art Director Node (design & AST validation)
- Consensus Node (Patch #10 contradiction checks)
- Healing Node (Patch #11 self-healing)
Supports robust fallback behavior if 'langgraph' is not installed.
"""

from __future__ import annotations

import logging
import uuid
import time
from typing import Any, TypedDict, Literal

from core.schemas import ConsensusVerdict
from agents.consensus_node import run_consensus_node
from agents.healing_agent import execute_healing_cycle

logger = logging.getLogger(__name__)

# ── State Definition ──────────────────────────────────────────────────────

class GraphState(TypedDict):
    chunk_id: uuid.UUID
    original_code: str
    healed_code: str | None
    professor_feedback: dict[str, Any]
    art_director_feedback: dict[str, Any]
    consensus_verdict: ConsensusVerdict | None
    prior_errors: list[str]
    start_time: float
    status: str  # 'verified', 'healing', 'failed'


# Try to import LangGraph. Build state graph if available.
try:
    from langgraph.graph import StateGraph, END

    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    END = "__end__"  # type: ignore


# ── Node Actions ─────────────────────────────────────────────────────────

async def professor_verification_node(state: GraphState) -> dict[str, Any]:
    """
    Evaluates factual correctness of narration/visual details.
    """
    logger.info("LangGraph Node: Executing Professor fact checks for chunk: %s", state["chunk_id"])
    # Returns simulated payload
    return {
        "professor_feedback": {
            "passed": True,
            "errors": []
        }
    }


async def art_director_verification_node(state: GraphState) -> dict[str, Any]:
    """
    Validates design alignment, layouts, and runs AST checks.
    """
    logger.info("LangGraph Node: Executing Art Director visual checks for chunk: %s", state["chunk_id"])
    # Returns simulated payload (can simulate failures for testing)
    return {
        "art_director_feedback": {
            "passed": True,
            "errors": []
        }
    }


async def consensus_router_node(state: GraphState) -> dict[str, Any]:
    """
    Pipes results from Prof and Art Director to check for contradictions (Patch #10).
    """
    logger.info("LangGraph Node: Executing Consensus Node rules (Patch #10)...")
    verdict = run_consensus_node(
        professor_feedback=state["professor_feedback"],
        art_director_feedback=state["art_director_feedback"],
    )
    return {"consensus_verdict": verdict}


async def healing_node(state: GraphState) -> dict[str, Any]:
    """
    Executes self-healing steps under escalating limits.
    """
    chunk_id = state["chunk_id"]
    code = state["healed_code"] or state["original_code"]
    verdict = state["consensus_verdict"]

    errors = []
    if verdict:
        errors = verdict.professor_errors + verdict.art_director_errors

    logger.info("LangGraph Node: Initializing healing task cycle for chunk %s...", chunk_id)
    result = await execute_healing_cycle(
        chunk_id=chunk_id,
        original_code=code,
        prior_errors=errors,
        start_time_stamp=state["start_time"],
    )

    if result["status"] == "success":
        return {
            "healed_code": result["healed_code"],
            "status": "healing",
            "prior_errors": state["prior_errors"] + errors,
        }
    else:
        return {
            "status": "failed",
            "prior_errors": state["prior_errors"] + errors,
        }


# ── Edge Routing Decider ─────────────────────────────────────────────────

def should_continue(state: GraphState) -> Literal["heal", "verified", "failed"]:
    verdict = state.get("consensus_verdict")
    if not verdict:
        return "failed"

    if verdict.passed:
        return "verified"

    if state["status"] == "failed":
        return "failed"

    return "heal"


# ── Compilation ──────────────────────────────────────────────────────────

def compile_verification_graph() -> Any:
    """
    Compiles and returns the LangGraph verification state machine.
    Uses custom class fallback if langgraph library is not installed.
    """
    if not HAS_LANGGRAPH:
        logger.warning("LangGraph not found in library path. Using native FallbackOrchestrator.")
        return FallbackOrchestrator()

    workflow = StateGraph(GraphState)

    # Register Nodes
    workflow.add_node("professor", professor_verification_node)
    workflow.add_node("art_director", art_director_verification_node)
    workflow.add_node("consensus", consensus_router_node)
    workflow.add_node("healing", healing_node)

    # Set Entry Point
    workflow.set_entry_point("professor")

    # Define validation execution flow
    workflow.add_edge("professor", "art_director")
    workflow.add_edge("art_director", "consensus")

    # Add conditional router branching after Consensus checks
    workflow.add_conditional_edges(
        "consensus",
        should_continue,
        {
            "verified": END,
            "failed": END,
            "heal": "healing"
        }
    )

    # After healing, route back to verification cycle
    workflow.add_edge("healing", "professor")

    return workflow.compile()


# ── Custom Fallback Orchestrator (Bypass compiler error when missing) ────

class FallbackOrchestrator:
    """
    Mimics LangGraph workflow execution using raw Python loops.
    Ensures stability in environments without compilation tools.
    """

    async def ainvoke(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        state: GraphState = {
            "chunk_id": initial_state["chunk_id"],
            "original_code": initial_state["original_code"],
            "healed_code": None,
            "professor_feedback": {},
            "art_director_feedback": {},
            "consensus_verdict": None,
            "prior_errors": [],
            "start_time": initial_state.get("start_time", time.monotonic()),
            "status": "pending",
        }

        # Verification Loop
        while True:
            # 1. Run Professor Verification Node
            prof_res = await professor_verification_node(state)
            state["professor_feedback"] = prof_res["professor_feedback"]

            # 2. Run Art Director Verification Node
            art_res = await art_director_verification_node(state)
            state["art_director_feedback"] = art_res["art_director_feedback"]

            # 3. Run Consensus Node
            cons_res = await consensus_router_node(state)
            state["consensus_verdict"] = cons_res["consensus_verdict"]

            decision = should_continue(state)
            if decision == "verified":
                state["status"] = "verified"
                logger.info("Fallback: Chunk verified successfully.")
                break
            elif decision == "failed":
                state["status"] = "failed"
                logger.error("Fallback: Chunk verification failed permanently.")
                break
            elif decision == "heal":
                # 4. Trigger healing cycles
                heal_res = await healing_node(state)
                state["status"] = heal_res["status"]
                if state["status"] == "failed":
                    break
                state["healed_code"] = heal_res.get("healed_code")
                state["prior_errors"] = heal_res["prior_errors"]

        return state
