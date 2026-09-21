from pathlib import Path

from utils import ffmpeg_utils


def test_system_ffmpeg_is_resolved_to_a_directory_for_ytdlp(monkeypatch):
    monkeypatch.setattr(ffmpeg_utils, "shutil", type("Shutil", (), {"which": lambda _name: "/usr/bin/ffmpeg"}))
    monkeypatch.setattr(Path, "exists", lambda _path: False)

    assert ffmpeg_utils.get_ffmpeg_dir() == Path("/usr/bin")
    assert ffmpeg_utils.get_ffmpeg_binary() == "/usr/bin/ffmpeg"
