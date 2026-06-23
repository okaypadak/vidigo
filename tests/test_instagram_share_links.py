from utils.download_service import classify_download_url
from utils.video_downloader import extract_instagram_username, resolve_instagram_shortcode


def test_classify_instagram_share_url_as_reel():
    result = classify_download_url("https://www.instagram.com/share/reel/example-token/")

    assert result["platform"] == "instagram"
    assert result["source_type"] == "reel"


def test_resolve_instagram_shortcode_uses_redirected_share_url(monkeypatch):
    monkeypatch.setattr(
        "utils.video_downloader._resolve_instagram_shared_url",
        lambda url, cookie_path=None: "https://www.instagram.com/reel/ABC123xyz_-/",
    )

    assert resolve_instagram_shortcode("https://www.instagram.com/share/reel/example-token/") == "ABC123xyz_-"


def test_classify_instagram_reels_tab_url_as_profile_reels():
    url = "https://www.instagram.com/batuhan.direct/reels/"

    result = classify_download_url(url)

    assert extract_instagram_username(url) == "batuhan.direct"
    assert result["platform"] == "instagram"
    assert result["source_type"] == "profile_reels"
