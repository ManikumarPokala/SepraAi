"""
SepraAI v2.7 — Semantic Splitter & Boundaries Tests

Tests boundary limits in semantic_splitter.py (Patch #5):
- Natural silence snapping target ~30s.
- Hard cap at 45s with word boundaries maintained.
- Grace extension up to 3s (48s total) to wait for better gaps.
"""

import pytest
from orchestration.semantic_splitter import split_narration_into_chunks, WordAlignment


def test_splitter_natural_silence_snap():
    """Asserts that the splitter snaps at a silence gap once the target duration is met."""
    # Target is 30s. Create words ending at 31s with a gap of 0.6s
    words: list[WordAlignment] = [
        {"word": "start", "start": 0.0, "end": 1.0, "score": 1.0},
        {"word": "mid", "start": 1.0, "end": 30.5, "score": 1.0},
        {"word": "gap", "start": 30.5, "end": 31.0, "score": 1.0},
        # Silence gap here: 31.6 - 31.0 = 0.6s
        {"word": "next", "start": 31.6, "end": 32.5, "score": 1.0},
        {"word": "end", "start": 32.5, "end": 35.0, "score": 1.0},
    ]

    chunks = split_narration_into_chunks(words)
    assert len(chunks) == 2
    # First chunk contains words up to "gap"
    assert [w["word"] for w in chunks[0]] == ["start", "mid", "gap"]
    assert [w["word"] for w in chunks[1]] == ["next", "end"]


def test_splitter_hard_cap_snap():
    """Asserts that the splitter forces a split at 45s on a word boundary if no silence exists."""
    # Create continuous words with 0.1s gaps (no silence > 0.5s) up to 50s
    words: list[WordAlignment] = []
    for sec in range(50):
        words.append({
            "word": f"word_{sec}",
            "start": float(sec),
            "end": float(sec) + 0.9,
            "score": 1.0
        })

    chunks = split_narration_into_chunks(words)
    assert len(chunks) > 1

    # Inspect first chunk. It must not violate the 48s grace cap,
    # and it must split exactly on a word boundary (no partial words).
    first_chunk_end = chunks[0][-1]["end"]
    # Should split near 45s hard cap since no silence lookahead is found
    assert first_chunk_end <= 46.0
    # Next chunk starts exactly at the next word
    assert chunks[1][0]["word"] == f"word_{len(chunks[0])}"


def test_splitter_grace_extension():
    """
    Asserts that the splitter delays splitting slightly (up to 3s grace)
    if a better silence gap exists just after the 45s mark.
    """
    words: list[WordAlignment] = []
    # Continuous words up to 44s
    for sec in range(44):
        words.append({
            "word": f"word_{sec}",
            "start": float(sec),
            "end": float(sec) + 0.9,
            "score": 1.0
        })

    # At 44s, we have a word ending at 44.9s.
    # Next word starts at 46.0s (a 1.1s silence gap!). This is inside the 3s grace window (45s to 48s).
    words.append({
        "word": "grace_word",
        "start": 46.0,
        "end": 47.0,
        "score": 1.0
    })
    words.append({
        "word": "final_word",
        "start": 47.1,
        "end": 48.5,
        "score": 1.0
    })

    chunks = split_narration_into_chunks(words)
    # The split should occur at the 44.9s mark (using lookahead for silence gap at 46.0s)
    # First chunk ends with "word_43" (since the gap starts after it)
    assert chunks[0][-1]["word"] == "word_43"
    assert chunks[1][0]["word"] == "grace_word"
