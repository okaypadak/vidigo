import pytest

from utils import video_downloader


def test_download_instaloader_post_uses_raw_video_urls(tmp_path):
    class FakeLoader:
        def download_pic(self, filename, url, mtime):
            with open(f"{filename}.mp4", "wb") as handle:
                handle.write(b"video")

    post = video_downloader.InstagramReelListItem(
        {
            "code": "ABC123",
            "media_type": 2,
            "video_versions": [{"url": "https://cdn.example/video.mp4?x=1"}],
            "caption": {"text": "caption"},
        },
        "batuhan.direct",
    )

    path = video_downloader._download_instaloader_post(FakeLoader(), post, str(tmp_path), "batuhan.direct")

    assert path.endswith("batuhan.direct_ABC123.mp4")
    assert (tmp_path / "batuhan.direct_ABC123.mp4").read_bytes() == b"video"


def test_profile_reels_raises_when_all_downloads_fail(monkeypatch, tmp_path):
    class FakeProfile:
        userid = 123

    class FakePost:
        shortcode = "ABC123"

    class FakeLoader:
        context = object()

    monkeypatch.setattr(video_downloader, "_build_instaloader", lambda *args, **kwargs: FakeLoader())
    monkeypatch.setattr(video_downloader.instaloader.Profile, "from_username", lambda *args, **kwargs: FakeProfile())
    monkeypatch.setattr(video_downloader, "_instagram_profile_reels_iterator", lambda *args, **kwargs: iter([FakePost()]))
    monkeypatch.setattr(video_downloader, "_is_reel_candidate", lambda post: True)

    def fail_download(*args, **kwargs):
        raise ConnectionError("cdn baglantisi kurulamadi")

    monkeypatch.setattr(video_downloader, "_download_instaloader_post", fail_download)

    with pytest.raises(RuntimeError, match="hicbir video indirilemedi"):
        video_downloader.download_instagram_profile_reels(
            "https://www.instagram.com/batuhan.direct/reels/",
            save_path=str(tmp_path),
            cookie_path=None,
        )


def test_profile_reels_graphql_empty_response_has_clear_error():
    with pytest.raises(RuntimeError, match="GraphQL bos yanit"):
        video_downloader._extract_instagram_reels_edges(None)


def test_profile_reels_graphql_error_response_has_clear_error():
    with pytest.raises(RuntimeError, match="execution error"):
        video_downloader._extract_instagram_reels_edges(
            {
                "errors": [{"message": "execution error"}],
                "data": None,
            }
        )


def test_profile_reels_raises_when_iterator_is_empty(monkeypatch, tmp_path):
    class FakeProfile:
        userid = 123

    class FakeLoader:
        context = object()

    monkeypatch.setattr(video_downloader, "_build_instaloader", lambda *args, **kwargs: FakeLoader())
    monkeypatch.setattr(video_downloader.instaloader.Profile, "from_username", lambda *args, **kwargs: FakeProfile())
    monkeypatch.setattr(video_downloader, "_instagram_profile_reels_iterator", lambda *args, **kwargs: iter(()))

    with pytest.raises(FileNotFoundError, match="indirilebilir reel bulunamadi"):
        video_downloader.download_instagram_profile_reels(
            "https://www.instagram.com/batuhan.direct/reels/",
            save_path=str(tmp_path),
            cookie_path=None,
        )
