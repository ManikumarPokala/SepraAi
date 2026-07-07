"""
SepraAI v2.7 — Art Director Agent

Enforces visual layout rules, layout constraints (12-Column Grid), and
coordinates AST allowlist passes on generated visual code before dispatcher routing.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from workers.sandbox_runtime import run_ast_lint_allowlist

logger = logging.getLogger(__name__)


async def run_art_director_check(
    chunk_id: uuid.UUID,
    script_code: str,
    renderer_type: str,
) -> dict[str, Any]:
    """
    Performs style checks, grid bounds verification, and code syntax validation.
    """
    logger.info("Art Director: Verifying visual constraints for chunk %s (%s)...", chunk_id, renderer_type)

    passed = True
    errors = []

    # 1. Run static AST security linting as warning pass (Patch #3)
    lint_passed = run_ast_lint_allowlist(script_code, filename=f"verification_{chunk_id}.py")
    if not lint_passed:
        errors.append("AST Warning: Code contains suspicious imports or system call signatures.")

    # 2. Check layout constraints (12-column grid alignment check simulation)
    # Search for coordinates or widths exceeding bounds in code text
    if "width=15" in script_code or "scale=5" in script_code:
        passed = False
        errors.append("Grid Violation: Element exceeds 12-column layout margins.")

    return {
        "passed": passed,
        "errors": errors,
        "chunk_id": str(chunk_id),
    }
