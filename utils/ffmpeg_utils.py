from pathlib import Path


def get_ffmpeg_dir():
    """
    Locate the bundled ffmpeg directory if it exists.
    Returns a Path or None when the directory is missing.
    """
    ffmpeg_dir = Path(__file__).resolve().parent.parent / "ffmpeg"
    return ffmpeg_dir if ffmpeg_dir.exists() else None


def get_ffmpeg_binary():
    """
    Return the best-effort path to the ffmpeg executable.
    Falls back to 'ffmpeg' so the system PATH is used if the bundle is absent.
    """
    ffmpeg_dir = get_ffmpeg_dir()
    if ffmpeg_dir:
        for name in ("ffmpeg.exe", "ffmpeg"):
            candidate = ffmpeg_dir / name
            if candidate.exists():
                return str(candidate)
    return "ffmpeg"
