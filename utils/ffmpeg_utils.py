import os
import shutil
from pathlib import Path

from utils.runtime_environment import is_windows


def _executable_name():
    return "ffmpeg.exe" if is_windows() else "ffmpeg"


def _configured_ffmpeg_binary():
    configured_binary = os.environ.get("TEXTFORGE_FFMPEG_BINARY", "").strip()
    if not configured_binary:
        return None

    binary = Path(os.path.expanduser(configured_binary))
    if binary.is_file():
        return binary

    resolved_binary = shutil.which(configured_binary)
    return Path(resolved_binary) if resolved_binary else None


def get_ffmpeg_dir():
    """
    Locate the bundled or system ffmpeg directory.

    yt-dlp validates ``ffmpeg_location`` as a filesystem path; passing the
    bare command name ``ffmpeg`` therefore fails even when it is on PATH.
    Return the containing directory of the resolved system binary instead.
    """
    configured_binary = _configured_ffmpeg_binary()
    if configured_binary:
        return configured_binary.parent

    # Yerel Windows paketi kendi ffmpeg.exe dosyasını taşıyabilir. Linux
    # konteynerde bu klasör kullanılmaz; ffmpeg apt ile sistem PATH'ine eklenir.
    if is_windows():
        ffmpeg_dir = Path(__file__).resolve().parent.parent / "ffmpeg"
        bundled_binary = ffmpeg_dir / _executable_name()
        if bundled_binary.is_file():
            return ffmpeg_dir

    system_ffmpeg = shutil.which(_executable_name())
    return Path(system_ffmpeg).parent if system_ffmpeg else None


def get_ffmpeg_binary():
    """
    Return the best-effort path to the ffmpeg executable.
    Falls back to the system PATH only when no resolved binary is available.
    """
    configured_binary = _configured_ffmpeg_binary()
    if configured_binary:
        return str(configured_binary)

    ffmpeg_dir = get_ffmpeg_dir()
    if ffmpeg_dir:
        executable_name = _executable_name()
        candidate = ffmpeg_dir / executable_name
        if candidate.is_file():
            return str(candidate)
    return shutil.which(_executable_name())


def get_ytdlp_ffmpeg_location():
    """yt-dlp için doğrulanmış ffmpeg dizinini, yoksa ``None`` döndürür."""
    ffmpeg_dir = get_ffmpeg_dir()
    return str(ffmpeg_dir) if ffmpeg_dir else None
