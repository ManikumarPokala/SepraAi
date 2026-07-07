"""
SepraAI v2.7 — Scene Checkpoint serialization helper

Coordinates reading, validating, and outputting JSON scene snapshots.
Enforces the Schema Rule by parsing through Pydantic strict validations.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.schemas import SceneCheckpointSchema

logger = logging.getLogger(__name__)


def serialize_scene_checkpoint(checkpoint: SceneCheckpointSchema) -> str:
    """
    Serializes a validated checkpoint schema into a clean JSON string.
    """
    # model_dump_json compiles through Pydantic strict assertions
    return checkpoint.model_dump_json()


def deserialize_scene_checkpoint(raw_json: str) -> SceneCheckpointSchema:
    """
    Deserializes a raw JSON string into a validated SceneCheckpointSchema.
    Rejects any unmapped properties or traversal attempts (Patch #4).
    """
    try:
        data = json.loads(raw_json)
        # model_validate enforces strict=True and extra='forbid'
        return SceneCheckpointSchema.model_validate(data)
    except Exception as e:
        logger.error("Failed to validate SceneCheckpoint structure: %s", e)
        raise ValueError(f"InvalidSceneCheckpointSchema: {e}")
