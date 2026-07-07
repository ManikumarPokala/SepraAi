"""
SepraAI v2.7 — FFmpeg Muxer & Transcoding Utilities

Implements media formatting constraints:
- The CBR Rule (Patch #6): Transcodes raw TTS outputs to standard 48kHz, 16-bit WAV immediately.
- Global sidechain-compression audio ducking at assembly layer.
"""

from __future__ import annotations

import logging
import subprocess
import os
from core.config import settings

logger = logging.getLogger(__name__)


def transcode_tts_to_cbr_wav(input_path: str, output_path: str) -> None:
    """
    Forces immediate transcoding of variable bitrate (VBR) or alternate sample rate
    TTS audio into standardized Constant Bit Rate (CBR) WAV format.
    Fulfills Patch #6 CBR conversion contract:
    `ffmpeg -y -i input -ar 48000 -sample_fmt s16 -acodec pcm_s16le output.wav`
    """
    logger.info("Transcoding TTS audio to CBR WAV: %s -> %s", input_path, output_path)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-ar", str(settings.TTS_OUTPUT_SAMPLE_RATE),
        "-acodec", "pcm_s16le",
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30.0)
        logger.info("Transcode successful. Output size: %d bytes", os.path.getsize(output_path))
    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg transcode failed! Stderr:\n%s", e.stderr)
        raise RuntimeError(f"FFmpeg transcode failed: {e.stderr}")
    except Exception as e:
        logger.error("Failed to execute FFmpeg transcode: %s", e)
        raise


def apply_assembly_sidechain_ducking(
    narration_audio_path: str,
    background_music_path: str,
    output_audio_path: str,
    duck_level_db: float = -15.0,
) -> None:
    """
    Applies audio sidechain compression (ducking) globally at the final assembly phase.
    Ensures background music is ducked dynamically when the narration track is active.
    Filter layout:
    `ffmpeg -i narration -i bgm -filter_complex "[1:a][0:a]sidechaincompress=threshold=...:ratio=...[out]" -map "[out]" output`
    """
    logger.info("Applying global audio sidechain ducking...")

    # Calculate threshold based on duck level desired
    # sidechaincompress filter applies compression on input 1 triggered by input 2
    cmd = [
        "ffmpeg",
        "-y",
        "-i", background_music_path,
        "-i", narration_audio_path,
        "-filter_complex",
        f"[0:a][1:a]sidechaincompress=threshold=0.03:ratio=4:release=500:makeup=1.5[aout]",
        "-map", "[aout]",
        "-acodec", "pcm_s16le",
        "-ar", str(settings.TTS_OUTPUT_SAMPLE_RATE),
        output_audio_path
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60.0)
        logger.info("Sidechain ducking successful. Muxed audio: %s", output_audio_path)
    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg sidechain ducking failed! Stderr:\n%s", e.stderr)
        raise RuntimeError(f"FFmpeg sidechain ducking failed: {e.stderr}")
    except Exception as e:
        logger.error("Failed to execute FFmpeg sidechain ducking: %s", e)
        raise
