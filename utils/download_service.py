import logging
import os

from utils.app_logging import log_exception, log_info
from utils.file_utils import save_download_record, upsert_download_record, upsert_manifest_item
from utils.video_downloader import (
    convert_items_to_audio,
    download_instagram_profile_reels,
    download_instagram_video,
    download_youtube_playlist,
    download_youtube_video,
    extract_instagram_shortcode,
    extract_instagram_username,
    is_instagram_url,
    resolve_cookie_file,
)
from utils.youtube_utils import (
    extract_youtube_video_id,
    is_youtube_playlist_url,
    is_youtube_url,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_ROOT = os.path.join(BASE_DIR, "downloads")
COOKIE_ROOT = os.path.join(os.path.expanduser("~"), "cookie")
logger = logging.getLogger(__name__)


def classify_download_url(url):
    normalized = (url or "").strip()
    if not normalized:
        raise ValueError("Bos URL indirilemez.")

    if is_youtube_url(normalized):
        if is_youtube_playlist_url(normalized):
            return {"platform": "youtube", "source_type": "playlist", "url": normalized}
        if extract_youtube_video_id(normalized):
            return {"platform": "youtube", "source_type": "video", "url": normalized}
        raise ValueError("Gecerli bir YouTube video veya playlist URL'si girin.")

    if is_instagram_url(normalized):
        if extract_instagram_shortcode(normalized):
            return {"platform": "instagram", "source_type": "reel", "url": normalized}
        if extract_instagram_username(normalized):
            return {"platform": "instagram", "source_type": "profile_reels", "url": normalized}
        raise ValueError("Instagram icin hesap URL'si veya reel URL'si girin.")

    raise ValueError("Su anda sadece YouTube ve Instagram URL'leri destekleniyor.")


def _platform_download_dir(platform):
    path = os.path.join(DOWNLOAD_ROOT, platform)
    os.makedirs(path, exist_ok=True)
    log_info(logger, "Platform indirme klasoru hazir", stage="download.prepare", platform=platform, path=path)
    return path


def _single_result(platform, source_type, url, item, download_dir, downloader):
    source_name = item.get("title") or item.get("video_id") or item.get("shortcode") or "download"
    return {
        "platform": platform,
        "source_type": source_type,
        "source_name": source_name,
        "source_url": url,
        "download_dir": download_dir,
        "downloader": downloader,
        "items": [item],
    }


def _persist_downloads(result):
    if not result.get("items"):
        raise FileNotFoundError("Indirilebilir video bulunamadi.")

    manifest_path = None
    downloader = result.get("downloader")
    log_info(
        logger,
        "Indirilen oge kayitlari yaziliyor",
        stage="download.persist",
        platform=result.get("platform"),
        source_type=result.get("source_type"),
        source_name=result.get("source_name"),
        item_count=len(result.get("items", [])),
    )
    for item in result.get("items", []):
        manifest_path, _ = upsert_manifest_item(
            result["platform"],
            result["source_name"],
            result["source_type"],
            result["source_url"],
            item,
            downloader=downloader,
            download_dir=result.get("download_dir"),
        )
        upsert_download_record(
            video_name=item.get("title") or item.get("file_name") or item.get("video_id") or "download",
            platform=result["platform"],
            source_type=result["source_type"],
            source_name=result["source_name"],
            source_url=result["source_url"],
            url=item.get("webpage_url") or item.get("source_url"),
            video_id=item.get("video_id") or item.get("shortcode"),
            shortcode=item.get("shortcode"),
            file_name=item.get("file_name"),
            file_path=item.get("file_path"),
            uploader=item.get("uploader"),
            downloader=downloader,
            manifest_path=manifest_path,
        )
        log_info(
            logger,
            "Indirilen oge kaydedildi",
            stage="download.persist",
            source_name=result.get("source_name"),
            file_name=item.get("file_name"),
            item_id=item.get("video_id") or item.get("shortcode"),
        )

    result["manifest_path"] = manifest_path
    result["item_count"] = len(result.get("items", []))
    log_info(
        logger,
        "Indirme kayitlari tamamlandi",
        stage="download.persist",
        manifest_path=manifest_path,
        item_count=result["item_count"],
    )
    return result


def _convert_result_to_audio(result):
    items = convert_items_to_audio(result.get("items", []))
    converted = dict(result)
    converted["items"] = items

    download_dir = converted.get("download_dir")
    if items:
        first_dir = os.path.dirname(items[0].get("file_path") or "")
        if first_dir:
            converted["download_dir"] = first_dir if len(items) == 1 else download_dir or first_dir

    downloader = converted.get("downloader") or "download"
    if "ffmpeg" not in downloader:
        converted["downloader"] = f"{downloader}+ffmpeg"
    return converted


def download_media(url, cookie_path=None, audio_only=False, item_callback=None):
    request = classify_download_url(url)
    platform = request["platform"]
    source_type = request["source_type"]
    log_info(logger, "URL siniflandirildi", stage="download.classify", url=url, platform=platform, source_type=source_type)
    resolved_cookie = resolve_cookie_file(platform, cookie_path=cookie_path, cookie_dir=COOKIE_ROOT)
    platform_dir = _platform_download_dir(platform)
    log_info(
        logger,
        "Downloader secimi yapildi",
        stage="download.prepare",
        platform=platform,
        source_type=source_type,
        cookie_file=resolved_cookie or "yok",
        download_dir=platform_dir,
    )

    if platform == "youtube":
        if source_type == "playlist":
            log_info(logger, "YouTube playlist indirme basladi", stage="download.execute", url=url)
            result = download_youtube_playlist(url, save_path=platform_dir, cookie_path=resolved_cookie)
            result["downloader"] = "yt-dlp"
        else:
            log_info(logger, "YouTube video indirme basladi", stage="download.execute", url=url)
            item = download_youtube_video(url, save_path=platform_dir, cookie_path=resolved_cookie)
            result = _single_result(platform, source_type, url, item, platform_dir, "yt-dlp")
    else:
        if source_type == "profile_reels":
            log_info(logger, "Instagram profil reels indirme basladi", stage="download.execute", url=url)
            result = download_instagram_profile_reels(
                url,
                save_path=platform_dir,
                cookie_path=resolved_cookie,
                audio_only=audio_only,
                item_callback=item_callback,
            )
            result["downloader"] = "instaloader"
        else:
            log_info(logger, "Instagram reel indirme basladi", stage="download.execute", url=url)
            item = download_instagram_video(url, save_path=platform_dir, cookie_path=resolved_cookie)
            result = _single_result(platform, source_type, url, item, platform_dir, "instaloader")

    result["cookie_file"] = resolved_cookie
    if audio_only and not (platform == "instagram" and source_type == "profile_reels"):
        log_info(
            logger,
            "Indirilen ogeler ses formatina donusturuluyor",
            stage="download.audio",
            platform=platform,
            source_type=source_type,
            item_count=len(result.get("items", [])),
        )
        result = _convert_result_to_audio(result)
    log_info(
        logger,
        "Indirme islemi tamamlandi, sonuc kayit asamasina geciliyor",
        stage="download.execute",
        source_name=result.get("source_name"),
        item_count=len(result.get("items", [])),
    )
    return _persist_downloads(result)


