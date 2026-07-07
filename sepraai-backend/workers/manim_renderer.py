"""
SepraAI v2.7 — Manim Renderer Coordinator

Builds, formats, and executes raw Manim CLI compile actions
within the process boundaries specified in the sandbox configuration.
"""

from __future__ import annotations

import logging
import os
from workers.sandbox_runtime import run_sandboxed_command

logger = logging.getLogger(__name__)


def render_manim_scene(
    script_path: str,
    output_directory: str,
    scene_name: str = "SceneChunk",
    quality: str = "h",
) -> str:
    """
    Compiles a Manim Python script into an MP4 video file.
    Wraps execution inside the sandbox boundary.
    """
    logger.info("Manim Renderer: Compiling scene %s from %s...", scene_name, script_path)

    output_filename = "output.mp4"
    cmd = [
        "manim",
        f"-q{quality}",
        "--media_dir", output_directory,
        "-o", output_filename,
        script_path,
        scene_name
    ]

    # Executes command within sandbox limits
    run_sandboxed_command(cmd, cwd=output_directory)

    # Resolve resulting output video path
    # Manim standard output structure: {media_dir}/videos/{script_name}/{quality}/{output_filename}
    script_basename = os.path.splitext(os.path.basename(script_path))[0]
    quality_folder = {
        "l": "480p15",
        "m": "720p30",
        "h": "1080p60",
        "k": "2160p60"
    }.get(quality, "1080p60")

    result_path = os.path.join(output_directory, "videos", script_basename, quality_folder, output_filename)
    return result_path
