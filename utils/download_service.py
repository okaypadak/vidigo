import logging
import os

from utils.app_logging import log_exception, log_info
from utils.file_utils import save_download_record, upsert_manifest_item
from utils.video_downloader import (
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
COOKIE_ROOT = os.path.join(BASE_DIR, "cookies")
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
        save_download_record(
            video_name=item.get("title") or item.get("file_name") or item.get("video_id") or "download",
            platform=result["platform"],
            source_type=result["source_type"],
            source_name=result["source_name"],
            source_url=result["source_url"],
            url=item.get("webpage_url") or item.get("source_url"),
            video_id=item.get("video_id") or item.get("shortcode"),
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


def download_media(url, cookie_path=None):
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
            result = download_instagram_profile_reels(url, save_path=platform_dir, cookie_path=resolved_cookie)
            result["downloader"] = "instaloader"
        else:
            log_info(logger, "Instagram reel indirme basladi", stage="download.execute", url=url)
            item = download_instagram_video(url, save_path=platform_dir, cookie_path=resolved_cookie)
            result = _single_result(platform, source_type, url, item, platform_dir, "instaloader")

    result["cookie_file"] = resolved_cookie
    log_info(
        logger,
        "Indirme islemi tamamlandi, sonuc kayit asamasina geciliyor",
        stage="download.execute",
        source_name=result.get("source_name"),
        item_count=len(result.get("items", [])),
    )
    return _persist_downloads(result)


def batch_download_media(urls, cookie_path=None):
    results = []
    total_urls = len(urls or [])
    log_info(logger, "Toplu indirme dongusu basladi", stage="batch.start", total_urls=total_urls)
    for index, raw_url in enumerate(urls or [], start=1):
        url = (raw_url or "").strip()
        if not url:
            continue
        try:
            log_info(logger, "Toplu indirme girdisi basladi", stage="batch.item.start", index=index, total=total_urls, url=url)
            payload = download_media(url, cookie_path=cookie_path)
            results.append(
                {
                    "url": url,
                    "platform": payload.get("platform"),
                    "source_type": payload.get("source_type"),
                    "source_name": payload.get("source_name"),
                    "item_count": payload.get("item_count", 0),
                    "manifest_path": payload.get("manifest_path"),
                    "download_dir": payload.get("download_dir"),
                    "status": "success",
                    "items": payload.get("items", []),
                }
            )
            log_info(
                logger,
                "Toplu indirme girdisi tamamlandi",
                stage="batch.item.done",
                index=index,
                total=total_urls,
                url=url,
                item_count=payload.get("item_count", 0),
            )
        except Exception as exc:
            log_exception(logger, "Toplu indirme girdisi basarisiz oldu", stage="batch.item.failed", index=index, total=total_urls, url=url)
            results.append(
                {
                    "url": url,
                    "platform": None,
                    "source_type": None,
                    "source_name": None,
                    "item_count": 0,
                    "manifest_path": None,
                    "download_dir": None,
                    "status": "error",
                    "error": str(exc),
                    "items": [],
                }
            )

    output = {
        "total": len(results),
        "success": sum(1 for item in results if item["status"] == "success"),
        "results": results,
    }
    log_info(logger, "Toplu indirme dongusu tamamlandi", stage="batch.done", total=output["total"], success=output["success"])
    return output
