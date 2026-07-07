"""
SepraAI v2.7 — Semantic Splitter & Chunk Boundary Engine

Implements the Bounded Chunking snaps and Word Boundary Grace protocols:
- Snaps boundaries to silence gaps (~30s target).
- Hard cap at 45s.
- Enforces snapping to WhisperX word boundaries (Patch #5), never mid-phoneme.
- Utilizes a 3s grace extension (up to 48s) to avoid mid-word splits.
"""

from __future__ import annotations

import logging
from typing import TypedDict, Any

from core.config import settings

logger = logging.getLogger(__name__)


class WordAlignment(TypedDict):
    word: str
    start: float  # Start time in seconds
    end: float    # End time in seconds
    score: float  # Confidence score / energy context


def split_narration_into_chunks(
    word_alignments: list[WordAlignment],
) -> list[list[WordAlignment]]:
    """
    Groups aligned words into distinct chunks based on targets and safety limits.
    Satisfies Patch #5: Snaps to word boundaries, uses 3s grace cap extension.
    """
    if not word_alignments:
        return []

    chunks: list[list[WordAlignment]] = []
    current_chunk: list[WordAlignment] = []
    chunk_start_time = word_alignments[0]["start"]

    i = 0
    total_words = len(word_alignments)

    while i < total_words:
        word = word_alignments[i]
        current_chunk.append(word)
        chunk_elapsed = word["end"] - chunk_start_time

        # If we have reached the target duration, try to find a natural silence gap
        is_last_word = (i == total_words - 1)
        next_word = word_alignments[i + 1] if not is_last_word else None

        # Silence gap check: gap between end of current word and start of next word
        silence_gap = 0.0
        if next_word:
            silence_gap = next_word["start"] - word["end"]

        # Check if we should split at this word boundary
        should_split = False

        if not is_last_word and next_word:
            # 1. Natural snap: target met and there is a decent silence gap
            if chunk_elapsed >= settings.CHUNK_TARGET_DURATION_S and silence_gap >= 0.5:
                logger.info(
                    "Splitter: Found natural silence gap of %.2fs at elapsed %.2fs.",
                    silence_gap,
                    chunk_elapsed,
                )
                should_split = True

            # 2. Hard cap enforcement with Grace Word Boundary snap (Patch #5)
            elif chunk_elapsed >= settings.CHUNK_HARD_CAP_DURATION_S:
                # We have hit the 45s hard cap.
                # Check if we can snap immediately (which is a word boundary since we are index-based)
                # But to avoid splitting mid-sentence/mid-phrase if a tiny bit more grace is needed,
                # we look at the next word.
                # The Grace Rule says: we can extend by up to 3s (up to 48s total) to split at a better boundary.
                # If extending by up to 3s would hit a silence gap, we wait.
                # Otherwise, we split right here because we are on a word boundary.
                # Let's inspect ahead for a silence gap within the grace window (3s)
                found_better_gap_in_grace = False
                lookahead_time = 0.0
                for k in range(i + 1, total_words - 1):
                    lookahead_word = word_alignments[k]
                    lookahead_next = word_alignments[k + 1]
                    lookahead_elapsed = lookahead_word["end"] - chunk_start_time
                    if lookahead_elapsed > settings.CHUNK_HARD_CAP_DURATION_S + settings.CHUNK_WORD_BOUNDARY_GRACE_S:
                        # Beyond grace limit (48s)
                        break
                    lookahead_gap = lookahead_next["start"] - lookahead_word["end"]
                    if lookahead_gap >= 0.4:
                        # Found a silence minimum inside the grace window! Let's defer split to that index
                        found_better_gap_in_grace = True
                        break

                if found_better_gap_in_grace:
                    # Defer split to hit the better silence gap
                    logger.debug("Splitter: Deferring split to catch better silence gap in grace window.")
                    should_split = False
                else:
                    # Split here — we are safely on a word boundary (Patch #5)
                    logger.warning(
                        "Splitter: Hard cap reached (%.2fs). Splitting on current word boundary.",
                        chunk_elapsed,
                    )
                    should_split = True

            # 3. Absolute Limit: if we exceed 48s, we MUST split immediately
            elif chunk_elapsed >= settings.CHUNK_HARD_CAP_DURATION_S + settings.CHUNK_WORD_BOUNDARY_GRACE_S:
                logger.warning(
                    "Splitter: Exceeded grace limit cap (%.2fs). Enforcing boundary split.",
                    chunk_elapsed,
                )
                should_split = True

        if should_split and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            if next_word:
                chunk_start_time = next_word["start"]
        elif is_last_word and current_chunk:
            chunks.append(current_chunk)

        i += 1

    logger.info("Splitter: Completed. Segmented %d words into %d chunks.", total_words, len(chunks))
    return chunks
