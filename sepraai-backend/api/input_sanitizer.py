"""
SepraAI v2.7 — Ingestion Sanitizer

Defends the API boundary by sanitizing incoming curriculum prompt parameters
against prompt injection, character escapes, or adversarial script injection attempts.
"""

from __future__ import annotations

import re
import html
import logging

logger = logging.getLogger(__name__)

# List of suspicious phrases commonly used in LLM jailbreaks or prompt injections
INJECTION_SIGNATURES = [
    r"ignore\s+(?:all\s+)?prior\s+instructions",
    r"system\s+(?:override|override\s+mode)",
    r"you\s+are\s+now\s+an\s+elite",
    r"disregard\s+previous",
    r"bypass\s+safety",
    r"as\s+an\s+ai\s+(?:model|assistant|agent)",
    r"new\s+rule\s+book",
    r"translate\s+this\s+instruction\s+and\s+execute",
]

INJECTION_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in INJECTION_SIGNATURES]


def sanitize_curriculum_prompt(prompt: str) -> str:
    """
    Cleans raw curriculum text and asserts against prompt injection strings.
    Raises ValueError if a signature match occurs.
    """
    if not prompt:
        return ""

    # 1. Clean HTML tags and entities to prevent rendering issues or visual pollution
    cleaned_prompt = html.escape(prompt)
    cleaned_prompt = cleaned_prompt.strip()

    # 2. Check for adversarial injection signatures
    for pattern in INJECTION_PATTERNS:
        if pattern.search(cleaned_prompt):
            logger.warning(
                "Ingestion Security Breach: Sanitization failed due to pattern match. "
                "Prompt segment flagged: %s",
                pattern.pattern,
            )
            raise ValueError(
                "PromptInjectionViolation: User query contains forbidden command override sequences."
            )

    return cleaned_prompt
