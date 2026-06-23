from utils import video_downloader


def test_list_youtube_video_urls_expands_playlist_url(monkeypatch):
    calls = []

    def fake_fetch(tab_url, ydl_opts):
        calls.append(tab_url)
        return {
            "id": "PLcmdy-D8C2PQ",
            "title": "Playlist",
            "channel": "Channel",
            "entries": [
                {"id": "abcdefghijk", "title": "One"},
                {"id": "lmnopqrstuv", "title": "Two", "uploader": "Uploader"},
            ],
        }

    monkeypatch.setattr(video_downloader, "_fetch_youtube_tab", fake_fetch)

    items = video_downloader.list_youtube_video_urls(
        "https://www.youtube.com/playlist?list=PLcmdy-D8C2PQ"
    )

    assert calls == ["https://www.youtube.com/playlist?list=PLcmdy-D8C2PQ"]
    assert items == [
        {
            "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "video_id": "abcdefghijk",
            "title": "One",
            "uploader": "Channel",
        },
        {
            "url": "https://www.youtube.com/watch?v=lmnopqrstuv",
            "video_id": "lmnopqrstuv",
            "title": "Two",
            "uploader": "Uploader",
        },
    ]


def test_list_youtube_video_urls_treats_watch_list_as_playlist(monkeypatch):
    calls = []

    def fake_fetch(tab_url, ydl_opts):
        calls.append(tab_url)
        return {
            "id": "PLcmdy-D8C2PQ",
            "entries": [{"id": "abcdefghijk", "title": "One"}],
        }

    monkeypatch.setattr(video_downloader, "_fetch_youtube_tab", fake_fetch)

    items = video_downloader.list_youtube_video_urls(
        "https://www.youtube.com/watch?v=zzzzzzzzzzz&list=PLcmdy-D8C2PQ"
    )

    assert calls == ["https://www.youtube.com/watch?v=zzzzzzzzzzz&list=PLcmdy-D8C2PQ"]
    assert [item["video_id"] for item in items] == ["abcdefghijk"]
