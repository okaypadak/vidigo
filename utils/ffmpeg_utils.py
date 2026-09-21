import shutil
from pathlib import Path


def get_ffmpeg_dir():
    """
    Locate the bundled or system ffmpeg directory.

    yt-dlp validates ``ffmpeg_location`` as a filesystem path; passing the
    bare command name ``ffmpeg`` therefore fails even when it is on PATH.
    Return the containing directory of the resolved system binary instead.
    """
    ffmpeg_dir = Path(__file__).resolve().parent.parent / "ffmpeg"
    if ffmpeg_dir.exists():
        return ffmpeg_dir

    system_ffmpeg = shutil.which("ffmpeg")
    return Path(system_ffmpeg).parent if system_ffmpeg else None


def get_ffmpeg_binary():
    """
    Return the best-effort path to the ffmpeg executable.
    Falls back to the system PATH only when no resolved binary is available.
    """
    ffmpeg_dir = get_ffmpeg_dir()
    if ffmpeg_dir:
        for name in ("ffmpeg.exe", "ffmpeg"):
            candidate = ffmpeg_dir / name
            if candidate.exists():
                return str(candidate)
    return shutil.which("ffmpeg") or "ffmpeg"
