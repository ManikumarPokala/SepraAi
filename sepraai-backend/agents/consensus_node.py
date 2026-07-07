"""
SepraAI v2.7 — LangGraph Agent Consensus Node

Implements 'The Agent Consensus Rule' (Patch #10):
Pipes verdicts from the Professor and Art Director into a unified node to detect
logical contradictions and resolve them, or trigger Layout Override to prevent deadlocks.
"""

from __future__ import annotations

import logging
from typing import Any

from core.schemas import ConsensusVerdict

logger = logging.getLogger(__name__)

# Basic antonym mapping to detect obvious contradictory requirements
CONTRADICTION_MAP = [
    ({"increase", "enlarge", "expand", "larger", "grow"}, {"decrease", "reduce", "shrink", "smaller", "contract"}),
    ({"show all", "more detail", "add text"}, {"hide", "remove text", "minimize", "less text"}),
    ({"fit grid", "restrict bounds", "clamp width"}, {"overflow", "scroll layout", "unbound width"}),
]


def detect_instruction_contradictions(prof_errors: list[str], art_errors: list[str]) -> bool:
    """
    Scans error instruction texts to spot logical contradictions that would cause a healing loop deadlock.
    """
    prof_text = " ".join(prof_errors).lower()
    art_text = " ".join(art_errors).lower()

    for prof_set, art_set in CONTRADICTION_MAP:
        # Check if the Professor mentions words from set A and Art Director mentions words from set B
        prof_match_a = any(word in prof_text for word in prof_set)
        art_match_b = any(word in art_text for word in art_set)

        # Or vice versa
        prof_match_b = any(word in prof_text for word in art_set)
        art_match_a = any(word in art_text for word in prof_set)

        if (prof_match_a and art_match_b) or (prof_match_b and art_match_a):
            logger.warning(
                "Consensus: Contradictory instructions detected between agents!\n"
                "Set A keywords in Prof/Art: %s\n"
                "Set B keywords in Prof/Art: %s",
                prof_set,
                art_set,
            )
            return True

    return False


def run_consensus_node(professor_feedback: dict[str, Any], art_director_feedback: dict[str, Any]) -> ConsensusVerdict:
    """
    Pipes agent feedback inputs and returns a consensus verdict (Patch #10).
    """
    prof_passed = professor_feedback.get("passed", True)
    art_passed = art_director_feedback.get("passed", True)

    prof_errors = professor_feedback.get("errors", [])
    art_errors = art_director_feedback.get("errors", [])

    if prof_passed and art_passed:
        logger.info("Consensus: Both Professor and Art Director verified visual chunk successfully.")
        return ConsensusVerdict(passed=True)

    # Detect logical locks/contradictions
    contradiction = detect_instruction_contradictions(prof_errors, art_errors)

    resolved_instructions = []
    if prof_errors:
        resolved_instructions.append(f"Professor Content Fixes: {' '.join(prof_errors)}")
    if art_errors:
        resolved_instructions.append(f"Art Director Style Fixes: {' '.join(art_errors)}")

    if contradiction:
        logger.warning("Consensus: Contradiction found. Triggering layout override to prevent infinite healing loop.")
        # Trigger layout override mode
        return ConsensusVerdict(
            passed=False,
            professor_errors=prof_errors,
            art_director_errors=art_errors,
            resolved_fix_instructions="CONTRADICTION DETECTED: Layout override requested. Split visual elements into sub-scenes or simplify display size constraints.",
            contradiction_detected=True,
            force_layout_override=True,
        )

    return ConsensusVerdict(
        passed=False,
        professor_errors=prof_errors,
        art_director_errors=art_errors,
        resolved_fix_instructions="\n".join(resolved_instructions),
        contradiction_detected=False,
        force_layout_override=False,
    )
