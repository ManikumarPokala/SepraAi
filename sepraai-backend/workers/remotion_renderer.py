"""
SepraAI v2.7 — Remotion Renderer Coordinator

Builds, formats, and executes Remotion video renders
within process boundaries specified in the sandbox configuration.
"""

from __future__ import annotations

import logging
import os
from workers.sandbox_runtime import run_sandboxed_command

logger = logging.getLogger(__name__)


def render_remotion_scene(
    entry_point_path: str,
    output_directory: str,
    composition_id: str = "Main",
) -> str:
    """
    Compiles a Remotion project config into an MP4 video file.
    Wraps execution inside the sandbox boundary.
    """
    logger.info("Remotion Renderer: Compiling composition %s from %s...", composition_id, entry_point_path)

    output_video_path = os.path.join(output_directory, "output.mp4")
    cmd = [
        "npx",
        "remotion",
        "render",
        entry_point_path,
        composition_id,
        output_video_path
    ]

    # Executes command within sandbox limits
    run_sandboxed_command(cmd, cwd=output_directory)

    return output_video_path
