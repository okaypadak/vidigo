import os

import start_web


def _patch_common_persistence(monkeypatch):
    monkeypatch.setattr(start_web, "_persist_transcript", lambda *args, **kwargs: None)
    monkeypatch.setattr(start_web, "upsert_manifest_item", lambda *args, **kwargs: ("manifest.json", {}))
    monkeypatch.setattr(start_web, "upsert_download_record", lambda *args, **kwargs: {})


def test_transcript_only_youtube_falls_back_to_whisper_when_subtitle_missing(monkeypatch, tmp_path):
    audio_path = tmp_path / "Channel" / "ses" / "Video.m4a"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_text("audio", encoding="utf-8")

    _patch_common_persistence(monkeypatch)
    monkeypatch.setattr(start_web, "classify_download_url", lambda url: {"platform": "youtube", "source_type": "video", "url": url})
    monkeypatch.setattr(start_web, "resolve_cookie_file", lambda *args, **kwargs: "cookie.txt")
    monkeypatch.setattr(start_web, "extract_youtube_channel_name", lambda url: "Channel")
    monkeypatch.setattr(start_web, "extract_youtube_video_id", lambda url: "abc123")
    monkeypatch.setattr(start_web, "_ytdlp_transcript_dir", lambda source_name=None: str(tmp_path / "Channel" / "transcript"))
    monkeypatch.setattr(start_web, "_youtube_subtitle_transcript", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("subtitle yok")))
    monkeypatch.setattr(start_web, "_download_mp3", lambda *args, **kwargs: str(audio_path))
    monkeypatch.setattr(start_web, "_whisper", lambda path: "whisper metni")

    item, manifest_path, cookie_file = start_web._process_audio_item(
        "https://www.youtube.com/watch?v=abc123",
        mode="transcript_only",
    )

    assert item["engine"] == "whisper"
    assert item["transcript"] == "whisper metni"
    assert item["audio_removed"] is True
    assert item["file_path"] is None
    assert item["removed_file_path"] == str(audio_path)
    assert not os.path.exists(audio_path)
    assert manifest_path == "manifest.json"
    assert cookie_file == "cookie.txt"


def test_download_youtube_does_not_fall_back_to_whisper_when_subtitle_missing(monkeypatch, tmp_path):
    audio_path = tmp_path / "Channel" / "ses" / "Video.m4a"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_text("audio", encoding="utf-8")

    _patch_common_persistence(monkeypatch)
    monkeypatch.setattr(start_web, "classify_download_url", lambda url: {"platform": "youtube", "source_type": "video", "url": url})
    monkeypatch.setattr(start_web, "resolve_cookie_file", lambda *args, **kwargs: "cookie.txt")
    monkeypatch.setattr(start_web, "extract_youtube_video_id", lambda url: "abc123")
    monkeypatch.setattr(start_web, "_download_mp3", lambda *args, **kwargs: str(audio_path))
    monkeypatch.setattr(start_web, "_youtube_subtitle_transcript", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("subtitle yok")))

    def fail_whisper(path):
        raise AssertionError("download modunda Whisper fallback calismamali")

    monkeypatch.setattr(start_web, "_whisper", fail_whisper)

    item, _, _ = start_web._process_audio_item(
        "https://www.youtube.com/watch?v=abc123",
        mode="download",
    )

    assert item["engine"] == "error"
    assert item["transcript"] is None
    assert item["file_path"] == str(audio_path)


def test_download_youtube_uses_existing_ytdlp_transcript_file_without_second_save(monkeypatch, tmp_path):
    audio_path = tmp_path / "Channel" / "ses" / "Video.m4a"
    transcript_path = tmp_path / "Channel" / "transcript" / "Video [abc123].txt"
    audio_path.parent.mkdir(parents=True)
    transcript_path.parent.mkdir(parents=True)
    audio_path.write_text("audio", encoding="utf-8")
    transcript_path.write_text("altyazi metni", encoding="utf-8")

    persist_calls = []
    monkeypatch.setattr(start_web, "_persist_transcript", lambda *args, **kwargs: persist_calls.append((args, kwargs)))
    monkeypatch.setattr(start_web, "upsert_manifest_item", lambda *args, **kwargs: ("manifest.json", {}))
    monkeypatch.setattr(start_web, "upsert_download_record", lambda *args, **kwargs: {})
    monkeypatch.setattr(start_web, "classify_download_url", lambda url: {"platform": "youtube", "source_type": "video", "url": url})
    monkeypatch.setattr(start_web, "resolve_cookie_file", lambda *args, **kwargs: "cookie.txt")
    monkeypatch.setattr(start_web, "extract_youtube_video_id", lambda url: "abc123")
    monkeypatch.setattr(start_web, "_download_mp3", lambda *args, **kwargs: str(audio_path))
    monkeypatch.setattr(start_web, "_ytdlp_transcript_dir", lambda source_name=None: str(transcript_path.parent))
    monkeypatch.setattr(start_web.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        start_web,
        "_youtube_subtitle_transcript",
        lambda *args, **kwargs: (
            {"file_path": str(transcript_path), "txt_path": str(transcript_path), "engine": "ytdlp_subtitle"},
            "altyazi metni",
        ),
    )

    item, _, _ = start_web._process_audio_item(
        "https://www.youtube.com/watch?v=abc123",
        mode="download",
    )

    assert item["engine"] == "ytdlp_subtitle"
    assert item["transcript"] == "altyazi metni"
    assert persist_calls == []


def test_transcript_only_instagram_keeps_audio_file(monkeypatch, tmp_path):
    audio_path = tmp_path / "vidigo" / "creator" / "ses" / "Reel.m4a"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_text("audio", encoding="utf-8")

    _patch_common_persistence(monkeypatch)
    monkeypatch.setattr(start_web, "classify_download_url", lambda url: {"platform": "instagram", "source_type": "reel", "url": url})
    monkeypatch.setattr(start_web, "resolve_cookie_file", lambda *args, **kwargs: "cookie.txt")
    monkeypatch.setattr(start_web, "_download_mp3", lambda *args, **kwargs: str(audio_path))
    monkeypatch.setattr(start_web, "_transcribe_downloaded_audio", lambda *args, **kwargs: ("whisper", "reel metni", None))

    item, _, _ = start_web._process_audio_item(
        "https://www.instagram.com/reel/DbQO2p7Mos7/",
        mode="transcript_only",
    )

    assert item["transcript"] == "reel metni"
    assert item["file_path"] == str(audio_path)
    assert "audio_removed" not in item
    assert audio_path.exists()
