"""
SepraAI v2.7 — Consensus Node Test Suite

Validates the Agent Consensus Rule (Patch #10):
- Confirms matching positive feedback passes.
- Confirms matching negative feedback escalates.
- Confirms contradiction detection triggers consensus layout override flags to prevent loops.
"""

import pytest
from agents.consensus_node import run_consensus_node, ConsensusVerdict


def test_consensus_success_agreement():
    """Asserts that matching positive feedback results in consensus validation."""
    prof_feedback = {"passed": True, "errors": []}
    art_feedback = {"passed": True, "errors": []}
    
    verdict = run_consensus_node(prof_feedback, art_feedback)
    assert verdict.passed is True
    assert verdict.force_layout_override is False
    assert len(verdict.professor_errors) == 0
    assert len(verdict.art_director_errors) == 0


def test_consensus_failed_agreement():
    """Asserts that matching negative feedback results in standard failure without deadlock."""
    prof_feedback = {"passed": False, "errors": ["Fact mismatch on line 5"]}
    art_feedback = {"passed": False, "errors": ["AST check warning"]}
    
    verdict = run_consensus_node(prof_feedback, art_feedback)
    assert verdict.passed is False
    assert verdict.force_layout_override is False
    assert "Fact mismatch" in verdict.professor_errors[0]
    assert "AST check" in verdict.art_director_errors[0]


def test_consensus_contradiction_resolution():
    """Asserts that contradictory feedback (e.g. alignment loops) triggers layout override."""
    # Simulation: Professor demands clamping width, Art director wants to overflow layout
    prof_feedback = {"passed": False, "errors": ["Must restrict bounds to fit grid"]}
    art_feedback = {"passed": False, "errors": ["Allow elements to overflow layout"]}
    
    verdict = run_consensus_node(prof_feedback, art_feedback)
    assert verdict.passed is False
    assert verdict.force_layout_override is True # Resolves loop by forcing layout scaling parameters
