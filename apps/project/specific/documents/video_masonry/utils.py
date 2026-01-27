# apps/project/specific/documents/video_masonry/utils.py (opcional)
from __future__ import annotations

import subprocess
from pathlib import Path

def strip_audio_ffmpeg(input_path: Path, output_path: Path) -> None:
    """
    Crea un nuevo video SIN pista de audio.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-c:v", "copy",
        "-an",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
