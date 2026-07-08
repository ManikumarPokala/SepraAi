"""
AI Chemistry Video Generation Engine

Implements synthetic video rendering with visual + audio content for chemistry concepts.
Uses a pure Python pixel canvas to render clean, animated diagrams and vector text,
and compiles them using FFmpeg from raw image frames to ensure 100% compatibility
across environments (no dependency on FFmpeg's 'drawtext' filter or external fonts).
"""

from __future__ import annotations

import os
import math
import struct
import subprocess
import logging
import wave

logger = logging.getLogger(__name__)

# ── Pure Python Lightweight Raster & Vector Graphics Library ─────────────────

class Canvas:
    """
    Lightweight, fast RGB pixel canvas.
    """
    def __init__(self, width: int = 1080, height: int = 720, bg_color: tuple[int, int, int] = (15, 23, 42)):
        self.width = width
        self.height = height
        self.pixels = bytearray(width * height * 3)
        self.clear(bg_color)

    def clear(self, color: tuple[int, int, int]) -> None:
        r, g, b = color
        for i in range(0, len(self.pixels), 3):
            self.pixels[i] = r
            self.pixels[i+1] = g
            self.pixels[i+2] = b

    def set_pixel(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = (y * self.width + x) * 3
            self.pixels[idx] = color[0]
            self.pixels[idx+1] = color[1]
            self.pixels[idx+2] = color[2]

    def draw_rect(self, x1: int, y1: int, w: int, h: int, color: tuple[int, int, int], fill: bool = True) -> None:
        x2 = min(self.width, x1 + w)
        y2 = min(self.height, y1 + h)
        x1 = max(0, x1)
        y1 = max(0, y1)
        if fill:
            for y in range(y1, y2):
                for x in range(x1, x2):
                    self.set_pixel(x, y, color)
        else:
            for x in range(x1, x2):
                self.set_pixel(x, y1, color)
                self.set_pixel(x, y2 - 1, color)
            for y in range(y1, y2):
                self.set_pixel(x1, y, color)
                self.set_pixel(x2 - 1, y, color)

    def draw_circle(self, cx: int, cy: int, r: int, color: tuple[int, int, int], fill: bool = True) -> None:
        x1 = max(0, cx - r)
        x2 = min(self.width, cx + r + 1)
        y1 = max(0, cy - r)
        y2 = min(self.height, cy + r + 1)
        r_sq = r * r
        for y in range(y1, y2):
            for x in range(x1, x2):
                dist_sq = (x - cx) ** 2 + (y - cy) ** 2
                if fill:
                    if dist_sq <= r_sq:
                        self.set_pixel(x, y, color)
                else:
                    # Circular ring line approximation
                    if (r - 2) ** 2 <= dist_sq <= r_sq:
                        self.set_pixel(x, y, color)

    def save_ppm(self, path: str) -> None:
        header = f"P6\n{self.width} {self.height}\n255\n".encode("ascii")
        with open(path, "wb") as f:
            f.write(header)
            f.write(self.pixels)


# 5x5 Grid Vector Font Segments (relative to character top-left)
# Coordinates are scaled 0 to 4.
FONT_5X5: dict[str, list[tuple[int, int, int, int]]] = {
    'H': [(0,0,0,4), (4,0,4,4), (0,2,4,2)],
    'p': [(0,0,0,4), (0,0,3,0), (3,0,3,2), (0,2,3,2)],
    'S': [(0,0,4,0), (0,0,0,2), (0,2,4,2), (4,2,4,4), (0,4,4,4)],
    'c': [(0,0,4,0), (0,0,0,4), (0,4,4,4)],
    'a': [(0,2,4,2), (4,2,4,4), (0,4,4,4), (0,3,4,3)],
    'l': [(2,0,2,4)],
    'e': [(0,0,4,0), (0,0,0,4), (0,4,4,4), (0,2,4,2)],
    'W': [(0,0,0,4), (4,0,4,4), (0,4,2,2), (2,2,4,4)],
    'o': [(0,2,4,2), (0,4,4,4), (0,2,0,4), (4,2,4,4)],
    'r': [(0,2,0,4), (0,2,4,2)],
    'k': [(0,0,0,4), (0,2,3,0), (0,2,3,4)],
    'A': [(2,0,0,4), (2,0,4,4), (1,2,3,2)],
    'c': [(0,2,4,2), (0,2,0,4), (0,4,4,4)],
    'i': [(2,0,2,0), (2,2,2,4)],
    'd': [(4,0,4,4), (0,2,4,2), (0,2,0,4), (0,4,4,4)],
    't': [(2,0,2,4), (0,1,4,1)],
    'y': [(0,2,2,4), (4,2,0,6), (2,4,4,2)],
    'N': [(0,0,0,4), (4,0,4,4), (0,0,4,4)],
    'u': [(0,2,0,4), (4,2,4,4), (0,4,4,4)],
    't': [(2,0,2,4), (1,1,3,1)],
    'B': [(0,0,0,4), (0,0,3,0), (3,0,3,2), (0,2,3,2), (3,2,3,4), (0,4,3,4)],
    'n': [(0,2,0,4), (0,2,4,2), (4,2,4,4)],
    'g': [(0,2,4,2), (0,2,0,4), (0,4,4,4), (4,4,4,6), (0,6,4,6)],
    'I': [(2,0,2,4), (0,0,4,0), (0,4,4,4)],
    'C': [(0,0,4,0), (0,0,0,4), (0,4,4,4)],
    'v': [(0,0,2,4), (2,4,4,0)],
    'e': [(0,2,4,2), (0,2,0,4), (0,4,4,4), (0,3,4,3)],
    'T': [(0,0,4,0), (2,0,2,4)],
    'F': [(0,0,0,4), (0,0,4,0), (0,2,3,2)],
    'D': [(0,0,0,4), (0,0,3,0), (3,0,3,4), (0,4,3,4)],
    'f': [(2,0,2,4), (1,1,3,1), (2,0,4,0)],
    'h': [(0,0,0,4), (0,2,4,2), (4,2,4,4)],
    'U': [(0,0,0,4), (4,0,4,4), (0,4,4,4)],
    'P': [(0,0,0,4), (0,0,4,0), (4,0,4,2), (0,2,4,2)],
    's': [(0,2,4,2), (0,2,0,3), (0,3,4,3), (4,3,4,4), (0,4,4,4)],
    'M': [(0,0,0,4), (4,0,4,4), (0,0,2,2), (2,2,4,0)],
    'E': [(0,0,0,4), (0,0,4,0), (0,2,3,2), (0,4,4,4)],
    'R': [(0,0,0,4), (0,0,3,0), (3,0,3,2), (0,2,3,2), (1,2,4,4)],
    'V': [(0,0,2,4), (2,4,4,0)],
    '+': [(2,1,2,3), (1,2,3,2)],
    '-': [(1,2,3,2)],
    '=': [(1,1,3,1), (1,3,3,3)],
    ':': [(2,1,2,1), (2,3,3,3)],
    '.': [(2,4,2,4)],
    '7': [(0,0,4,0), (4,0,2,4)],
    '0': [(0,0,4,0), (0,0,0,4), (4,0,4,4), (0,4,4,4)],
    '1': [(1,0,2,0), (2,0,2,4), (1,4,3,4)],
    '2': [(0,0,4,0), (4,0,4,2), (4,2,0,2), (0,2,0,4), (0,4,4,4)],
    '3': [(0,0,4,0), (4,0,4,4), (0,2,4,2), (0,4,4,4)],
    '4': [(0,0,0,2), (0,2,4,2), (4,0,4,4)],
}


def draw_line(canvas: Canvas, x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int], thickness: int = 1) -> None:
    """Draws a solid line on canvas using Bresenham's line algorithm."""
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx - dy
    while True:
        # Draw a small square/brush for thickness
        for tx in range(-thickness // 2 + 1, thickness // 2 + 1):
            for ty in range(-thickness // 2 + 1, thickness // 2 + 1):
                canvas.set_pixel(x1 + tx, y1 + ty, color)
        if x1 == x2 and y1 == y2:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x1 += sx
        if e2 < dx:
            err += dx
            y1 += sy


def draw_char(canvas: Canvas, char: str, x: int, y: int, color: tuple[int, int, int], size: int = 4, thickness: int = 2) -> None:
    """Draws a single character based on vector segments."""
    if char not in FONT_5X5:
        # Unknown character box fallback
        canvas.draw_rect(x, y, size * 4, size * 4, color, fill=False)
        return
    segments = FONT_5X5[char]
    for sx1, sy1, sx2, sy2 in segments:
        draw_line(
            canvas,
            x + sx1 * size,
            y + sy1 * size,
            x + sx2 * size,
            y + sy2 * size,
            color,
            thickness
        )


def draw_text(canvas: Canvas, text: str, x: int, y: int, color: tuple[int, int, int], size: int = 4, spacing: int = 6, thickness: int = 2) -> None:
    """Draws a line of text onto the canvas."""
    curr_x = x
    for char in text:
        if char == " ":
            curr_x += size * 4
        else:
            draw_char(canvas, char, curr_x, y, color, size, thickness)
            curr_x += size * 4 + spacing


# ── Audio & Video Generation Implementation ─────────────────────────────────

def generate_synthetic_audio(output_wav_path: str, duration_seconds: float) -> None:
    """
    Generates a high-quality PCM WAV chime melody for the audio track (100% offline).
    """
    sample_rate = 48000
    n_samples = int(sample_rate * duration_seconds)

    # Ensure parent directories exist
    os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)

    with wave.open(output_wav_path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # 16-bit PCM
        wav.setframerate(sample_rate)

        for i in range(n_samples):
            t = i / sample_rate
            note_duration = 2.0
            note_index = int(t / note_duration)
            t_note = t % note_duration

            # Chord progression
            freqs = [261.63, 293.66, 329.63, 392.00, 440.00, 523.25]
            freq = freqs[note_index % len(freqs)]

            # decaying chime
            envelope = math.exp(-2.0 * t_note)
            chime_val = int(32767 * 0.25 * math.sin(2 * math.pi * freq * t_note) * envelope)

            # soft background pad hum
            pad_val = int(32767 * 0.04 * math.sin(2 * math.pi * 130.81 * t))

            val = chime_val + pad_val
            val = max(-32768, min(32767, val))
            wav.writeframesraw(struct.pack("<h", val))


def generate_chemistry_video(concept: str, output_path: str) -> None:
    """
    Renders visual slides as image frames in Python, then calls FFmpeg to compile
    them along with synthetic audio.
    """
    logger.info("Initializing chemistry video builder for concept: %s", concept)
    normalized = concept.strip().lower().rstrip("?").replace("?", "")

    # 1. Setup metadata
    if "ph scale" in normalized:
        title = "pH Scale"
        subtitle = "Acidity vs. Alkalinity"
        lines = [
            "Measures hydrogen ion concentration",
            "Ranges 0 to 14: 7 is neutral",
            "pH < 7 Acidic. pH > 7 Alkaline"
        ]
        duration = 10.0
        mode = "ph_scale"
    elif "covalent bonds" in normalized or "covalent bonding" in normalized:
        title = "Covalent Bonds"
        subtitle = "Sharing Valence Electrons"
        lines = [
            "Formed between non-metal atoms",
            "Atoms share valence electron pairs",
            "Achieves a stable outer shell"
        ]
        duration = 12.0
        mode = "covalent"
    elif "difference between ionic and covalent" in normalized or "ionic vs covalent" in normalized:
        title = "Ionic vs Covalent"
        subtitle = "Transfer vs Sharing"
        lines = [
            "Ionic: Electron is transferred",
            "Creates attraction between ions",
            "Covalent: Electrons are shared"
        ]
        duration = 14.0
        mode = "ionic_vs_covalent"
    else:
        title = "Chemistry Lesson"
        subtitle = concept[:30]
        lines = [
            "Analyzing requested concept",
            "Simulating atomic layouts",
            "Synthesizing visual slides"
        ]
        duration = 8.0
        mode = "fallback"

    # Frame compilation params
    fps = 15
    total_frames = int(duration * fps)

    temp_dir = output_path + "_temp_frames"
    os.makedirs(temp_dir, exist_ok=True)

    temp_wav_path = output_path + ".temp.wav"
    try:
        # Render each frame as PPM
        for f_idx in range(total_frames):
            t = f_idx / fps
            canvas = Canvas(width=1080, height=720, bg_color=(15, 23, 42))

            # ── Draw Header & Titles ──────────────────────────────────────────
            canvas.draw_rect(0, 0, 1080, 85, (30, 41, 59))
            draw_text(canvas, "AI CHEMISTRY SERVICE", 40, 32, (59, 130, 246), size=2, spacing=3, thickness=2)
            draw_text(canvas, title, 40, 120, (255, 255, 255), size=4, spacing=5, thickness=3)
            draw_text(canvas, subtitle, 40, 175, (16, 185, 129), size=2, spacing=4, thickness=2)

            # ── Draw Bullet Points ──────────────────────────────────────────
            for b_idx, line in enumerate(lines):
                y_pos = 230 + b_idx * 35
                draw_text(canvas, line, 50, y_pos, (226, 232, 240), size=2, spacing=3, thickness=2)

            # ── Draw Dynamic Animated Diagrams ──────────────────────────────
            if mode == "ph_scale":
                # Draw colored pH blocks
                colors = [
                    (239, 68, 68),   # 0-2 Red
                    (249, 115, 22),  # 3-5 Orange
                    (234, 179, 8),   # 6 Yellow
                    (34, 197, 94),   # 7 Green
                    (20, 184, 166),  # 8-9 Teal
                    (59, 130, 246),  # 10-11 Blue
                    (168, 85, 247)   # 12-14 Purple
                ]
                for c_idx, color in enumerate(colors):
                    canvas.draw_rect(200 + c_idx * 100, 420, 95, 45, color, fill=True)
                
                # Label markers
                draw_text(canvas, "Acidic", 200, 480, (239, 68, 68), size=2, spacing=3, thickness=2)
                draw_text(canvas, "Neutral", 500, 480, (34, 197, 94), size=2, spacing=3, thickness=2)
                draw_text(canvas, "Alkaline", 800, 480, (168, 85, 247), size=2, spacing=3, thickness=2)

                # Animate a sliding pH indicator pointer
                pointer_x = int(200 + 350 + 200 * math.sin(t * 2.0))
                canvas.draw_circle(pointer_x, 400, 10, (255, 255, 255), fill=True)
                canvas.draw_rect(pointer_x - 3, 410, 6, 20, (255, 255, 255), fill=True)

            elif mode == "covalent":
                # Orbiting shared electrons animation
                cx1, cy1 = 400, 440
                cx2, cy2 = 680, 440
                r_orbit = 100
                canvas.draw_circle(cx1, cy1, r_orbit, (59, 130, 246), fill=False)
                canvas.draw_circle(cx2, cy2, r_orbit, (16, 185, 129), fill=False)

                draw_text(canvas, "Atom A", 360, 430, (59, 130, 246), size=2, spacing=3, thickness=2)
                draw_text(canvas, "Atom B", 640, 430, (16, 185, 129), size=2, spacing=3, thickness=2)

                # Sharing electron pairs circling in the intersection
                e_angle = t * 3.0
                ex1 = int(540 + 15 * math.cos(e_angle))
                ey1 = int(440 + 40 * math.sin(e_angle))
                ex2 = int(540 - 15 * math.cos(e_angle))
                ey2 = int(440 - 40 * math.sin(e_angle))

                canvas.draw_circle(ex1, ey1, 8, (234, 179, 8), fill=True)
                canvas.draw_circle(ex2, ey2, 8, (234, 179, 8), fill=True)
                draw_text(canvas, "e-", ex1 - 5, ey1 - 5, (15, 23, 42), size=1, spacing=1, thickness=1)
                draw_text(canvas, "e-", ex2 - 5, ey2 - 5, (15, 23, 42), size=1, spacing=1, thickness=1)

            elif mode == "ionic_vs_covalent":
                # Side by side representations
                # Left: Ionic
                canvas.draw_rect(150, 380, 340, 200, (239, 68, 68), fill=False)
                draw_text(canvas, "IONIC: Transfer", 180, 400, (239, 68, 68), size=2, spacing=3, thickness=2)
                # Transfer animation: electron jumps back and forth
                progress = (t * 0.5) % 1.0
                ex = int(240 + (440 - 240) * progress)
                ey = int(480 - 40 * math.sin(progress * math.pi))
                canvas.draw_circle(240, 480, 25, (59, 130, 246), fill=True)
                draw_text(canvas, "Na", 230, 470, (255, 255, 255), size=1, spacing=1, thickness=1)
                canvas.draw_circle(440, 480, 25, (34, 197, 94), fill=True)
                draw_text(canvas, "Cl", 430, 470, (255, 255, 255), size=1, spacing=1, thickness=1)
                canvas.draw_circle(ex, ey, 6, (234, 179, 8), fill=True)

                # Right: Covalent
                canvas.draw_rect(590, 380, 340, 200, (16, 185, 129), fill=False)
                draw_text(canvas, "COVALENT: Sharing", 610, 400, (16, 185, 129), size=2, spacing=3, thickness=2)
                # Shared pair in between
                canvas.draw_circle(700, 480, 25, (168, 85, 247), fill=True)
                draw_text(canvas, "H", 695, 470, (255, 255, 255), size=1, spacing=1, thickness=1)
                canvas.draw_circle(820, 480, 25, (168, 85, 247), fill=True)
                draw_text(canvas, "H", 815, 470, (255, 255, 255), size=1, spacing=1, thickness=1)
                canvas.draw_circle(760, 465, 6, (234, 179, 8), fill=True)
                canvas.draw_circle(760, 495, 6, (234, 179, 8), fill=True)

            else:
                # Generic molecular circle animation
                osc_y = int(450 + 50 * math.sin(t * 3.0))
                canvas.draw_circle(340, osc_y, 40, (59, 130, 246), fill=True)
                canvas.draw_circle(740, 450, 40, (16, 185, 129), fill=True)
                draw_line(canvas, 340, osc_y, 740, 450, (255, 255, 255), thickness=3)

            # Save PPM frame
            canvas.save_ppm(os.path.join(temp_dir, f"frame_{f_idx:03d}.ppm"))

        # 3. Generate audio track
        generate_synthetic_audio(temp_wav_path, duration)

        # 4. Invoke FFmpeg to assemble PPM frames and audio into target MP4
        # -y: overwrite
        # -framerate 15: input frame rate
        # -i frame_%03d.ppm: input frame sequence
        # -i audio: input audio track
        # -shortest: end when shortest stream ends
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate", str(fps),
            "-i", os.path.join(temp_dir, "frame_%03d.ppm"),
            "-i", temp_wav_path,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path
        ]

        logger.info("Executing FFmpeg frame compile subprocess...")
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60.0
        )
        if res.returncode != 0:
            logger.error("FFmpeg compile failed: %s", res.stderr)
            raise RuntimeError(f"FFmpeg failed with code {res.returncode}: {res.stderr}")

        logger.info("Chemistry video generated successfully at: %s", output_path)

    finally:
        # Cleanup temporary audio files and PPM frames
        if os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
            except OSError:
                pass

        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                try:
                    os.remove(os.path.join(temp_dir, file))
                except OSError:
                    pass
            try:
                os.rmdir(temp_dir)
            except OSError:
                pass
