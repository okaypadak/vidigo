import os
import textwrap

from utils.video_downloader import download_youtube_transcript_ytdlp


def test_download_youtube_transcript_ytdlp_passes_cookiefile(monkeypatch, tmp_path):
    captured_opts = {}
    calls = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured_opts.update(opts)
            calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            if not download:
                return {
                    "id": "abc123",
                    "title": "Video",
                    "webpage_url": url,
                    "language": "en",
                    "automatic_captions": {"en": [{"ext": "vtt"}]},
                }
            vtt_path = tmp_path / "Video [abc123].en.vtt"
            vtt_path.write_text(
                textwrap.dedent(
                    """\
                    WEBVTT

                    00:00:00.000 --> 00:00:01.000
                    hello
                    """
                ),
                encoding="utf-8",
            )
            return {"id": "abc123", "title": "Video", "webpage_url": url}

    monkeypatch.setattr("utils.video_downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)

    items = download_youtube_transcript_ytdlp(
        "https://www.youtube.com/watch?v=abc123",
        save_path=str(tmp_path),
        cookie_path="C:/cookies/youtube.txt",
    )

    assert captured_opts["cookiefile"] == "C:/cookies/youtube.txt"
    assert items[0]["engine"] == "ytdlp_subtitle"
    assert os.path.isfile(items[0]["txt_path"])
    assert items[0]["transcript"] == "hello"
    assert calls[-1]["subtitleslangs"] == ["en"]


def test_download_youtube_transcript_ytdlp_uses_default_video_language(monkeypatch, tmp_path):
    captured_opts = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured_opts.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            if not download:
                return {
                    "id": "abc123",
                    "title": "Video",
                    "webpage_url": url,
                    "language": "az",
                    "automatic_captions": {"az": [{"ext": "vtt"}], "tr": [{"ext": "vtt"}]},
                }
            vtt_path = tmp_path / "Video [abc123].az.vtt"
            vtt_path.write_text(
                textwrap.dedent(
                    """\
                    WEBVTT

                    00:00:00.000 --> 00:00:01.000
                    salam
                    """
                ),
                encoding="utf-8",
            )
            return {"id": "abc123", "title": "Video", "webpage_url": url, "language": "az"}

    monkeypatch.setattr("utils.video_downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)

    items = download_youtube_transcript_ytdlp(
        "https://www.youtube.com/watch?v=abc123",
        save_path=str(tmp_path),
        cookie_path=None,
    )

    assert captured_opts["subtitleslangs"] == ["az"]
    assert items[0]["transcript"] == "salam"


def test_download_youtube_transcript_ytdlp_prefers_original_caption_variant(monkeypatch, tmp_path):
    captured_opts = {}

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured_opts.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            if not download:
                return {
                    "id": "abc123",
                    "title": "Video",
                    "webpage_url": url,
                    "language": "tr",
                    "automatic_captions": {"tr": [{"ext": "vtt"}], "tr-orig": [{"ext": "vtt"}]},
                }
            vtt_path = tmp_path / "Video [abc123].tr-orig.vtt"
            vtt_path.write_text(
                textwrap.dedent(
                    """\
                    WEBVTT

                    00:00:00.000 --> 00:00:01.000
                    merhaba
                    """
                ),
                encoding="utf-8",
            )
            return {"id": "abc123", "title": "Video", "webpage_url": url, "language": "tr"}

    monkeypatch.setattr("utils.video_downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)

    items = download_youtube_transcript_ytdlp(
        "https://www.youtube.com/watch?v=abc123",
        save_path=str(tmp_path),
        cookie_path=None,
    )

    assert captured_opts["subtitleslangs"] == ["tr-orig"]
    assert items[0]["transcript"] == "merhaba"


def test_download_youtube_transcript_ytdlp_falls_back_when_first_language_has_no_file(monkeypatch, tmp_path):
    attempted_languages = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            if not download:
                return {
                    "id": "abc123",
                    "title": "Video",
                    "webpage_url": url,
                    "language": "tr",
                    "automatic_captions": {"tr": [{"ext": "vtt"}], "az": [{"ext": "vtt"}]},
                }
            langs = self.opts.get("subtitleslangs") or []
            attempted_languages.append(langs)
            if langs == ["az"]:
                vtt_path = tmp_path / "Video [abc123].az.vtt"
                vtt_path.write_text(
                    textwrap.dedent(
                        """\
                        WEBVTT

                        00:00:00.000 --> 00:00:01.000
                        salam
                        """
                    ),
                    encoding="utf-8",
                )
            return {"id": "abc123", "title": "Video", "webpage_url": url, "language": "tr"}

    monkeypatch.setattr("utils.video_downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)

    items = download_youtube_transcript_ytdlp(
        "https://www.youtube.com/watch?v=abc123",
        save_path=str(tmp_path),
        cookie_path=None,
    )

    assert attempted_languages[:2] == [["tr"], ["az"]]
    assert items[0]["transcript"] == "salam"
