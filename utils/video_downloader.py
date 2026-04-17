import http.cookiejar
import logging
import os
import re
import subprocess
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import instaloader
import yt_dlp

from utils.app_logging import log_info, log_warning
from utils.ffmpeg_utils import get_ffmpeg_binary, get_ffmpeg_dir
from utils.youtube_utils import extract_youtube_playlist_id

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
INSTAGRAM_RESERVED_PATHS = {
    "accounts",
    "about",
    "developer",
    "developers",
    "direct",
    "explore",
    "privacy",
    "reel",
    "reels",
    "stories",
    "tv",
    "p",
}

logger = logging.getLogger(__name__)


def sanitize_filename(name):
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", str(name or "audio"))
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "audio"


def build_unique_filepath(directory, title, extension):
    safe_title = sanitize_filename(title)
    candidate = os.path.join(directory, f"{safe_title}{extension}")
    if not os.path.exists(candidate):
        return candidate

    counter = 2
    while True:
        candidate = os.path.join(directory, f"{safe_title} ({counter}){extension}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def extract_instagram_shortcode(url):
    parsed = _parse_url(url)
    if not parsed:
        return None

    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]

    if "instagram.com" not in host or len(parts) < 2:
        return None

    if parts[0] in ("p", "reel", "reels", "tv"):
        return parts[1]

    return None


def _parse_url(url):
    if not url:
        return None

    if "://" not in url:
        url = "https://" + url

    return urlparse(url)


def is_instagram_url(url):
    parsed = _parse_url(url)
    if not parsed:
        return False

    return "instagram.com" in parsed.netloc.lower()


def extract_instagram_username(url):
    parsed = _parse_url(url)
    if not parsed:
        return None

    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]
    if "instagram.com" not in host or len(parts) != 1:
        return None

    username = parts[0].strip()
    if not username or username.lower() in INSTAGRAM_RESERVED_PATHS:
        return None

    return username


def _instagram_public_profile_status(username):
    profile_url = f"https://www.instagram.com/{username}/"
    request = Request(
        profile_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except URLError:
        return None


def _raise_instagram_profile_lookup_error(username, cookie_path):
    status = _instagram_public_profile_status(username)
    log_warning(
        logger,
        "Instagram profil metadata sorgusu basarisiz oldu",
        stage="instagram.profile",
        username=username,
        public_status=status or "unreachable",
        cookie_file=cookie_path or "yok",
    )

    if status == 404:
        raise ValueError(f"Instagram profili bulunamadi: {username}")

    if status in (200, 401, 403, 429):
        if cookie_path:
            raise ValueError(
                "Instagram profil URL'si tanindi ancak reels listesi alinmadi. "
                "Instagram anonim GraphQL erisimini engelledi veya cookie gecersiz/eskimis olabilir. "
                "~/cookie/instagram.txt dosyasini yenileyip tekrar deneyin."
            )
        raise ValueError(
            "Instagram profil URL'si tanindi ancak reels listesi alinmadi. "
            "Instagram bu profil icin giris gerektiriyor veya anonim GraphQL erisimini engelliyor. "
            "~/cookie/instagram.txt ekleyip tekrar deneyin."
        )

    raise ValueError(
        "Instagram profil URL'si tanindi ancak profil reels verisi su an alinamadi. "
        "Instagram tarafinda gecici engel veya baglanti sorunu olabilir."
    )


def resolve_cookie_file(platform, cookie_path=None, cookie_dir="~/cookie"):
    candidates = []
    if cookie_path:
        candidates.append(cookie_path)

    expanded_cookie_dir = os.path.abspath(os.path.expanduser(cookie_dir))

    base_names = {
        "youtube": ("youtube.txt", "youtube_cookies.txt", "cookies.txt"),
        "instagram": ("instagram.txt", "instagram_cookies.txt", "cookies.txt"),
    }.get(platform, ("cookies.txt",))

    for name in base_names:
        candidates.append(os.path.join(expanded_cookie_dir, name))

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            resolved = os.path.abspath(candidate)
            log_info(logger, "Cookie dosyasi bulundu", stage="cookie.resolve", platform=platform, cookie_file=resolved)
            return resolved

    log_info(logger, "Cookie dosyasi bulunamadi, cookiesiz devam edilecek", stage="cookie.resolve", platform=platform)
    return None


def _iter_directory_files(directory):
    return {
        os.path.join(directory, filename)
        for filename in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, filename))
    }


def _find_latest_video_file(directory, stem=None, ignore_paths=None):
    ignore_paths = ignore_paths or set()
    matches = []
    for filename in os.listdir(directory):
        path = os.path.join(directory, filename)
        if path in ignore_paths or not os.path.isfile(path):
            continue
        file_stem, extension = os.path.splitext(filename)
        if extension.lower() not in VIDEO_EXTENSIONS:
            continue
        if stem and file_stem != stem:
            continue
        matches.append(path)

    return max(matches, key=os.path.getmtime) if matches else None


def _download_instaloader_post(loader, post, output_dir, target):
    existing_files = _iter_directory_files(output_dir)
    log_info(
        logger,
        "Instaloader gonderi indirme basladi",
        stage="instagram.download.post",
        shortcode=post.shortcode,
        target=target,
        output_dir=output_dir,
    )
    loader.download_post(post, target=target)

    expected_stem = f"{target}_{post.shortcode}"
    video_path = _find_latest_video_file(output_dir, stem=expected_stem, ignore_paths=existing_files) or _find_latest_video_file(
        output_dir,
        stem=expected_stem,
    )
    log_info(
        logger,
        "Instaloader gonderi indirme tamamlandi",
        stage="instagram.download.post",
        shortcode=post.shortcode,
        file_path=video_path or "bulunamadi",
    )
    return video_path


def _apply_instagram_cookiefile(loader, cookie_path):
    if not cookie_path:
        log_info(logger, "Instagram oturumu cookiesiz kuruluyor", stage="instagram.session")
        return

    cookie_jar = http.cookiejar.MozillaCookieJar(cookie_path)
    cookie_jar.load(ignore_discard=True, ignore_expires=True)
    cookie_map = {}
    for cookie in cookie_jar:
        if cookie.name and cookie.value:
            cookie_map[cookie.name] = cookie.value

    loader.context.update_cookies(cookie_map)

    csrf_token = cookie_map.get("csrftoken")
    if csrf_token:
        loader.context._session.headers.update({"X-CSRFToken": csrf_token})

    username = loader.test_login()
    if not username:
        raise ValueError(
            "Instagram cookie dosyasi yuklendi ancak oturum dogrulanamadi. "
            "~/cookie/instagram.txt dosyasini yenileyin."
        )

    loader.context.username = username
    ds_user_id = cookie_map.get("ds_user_id")
    if ds_user_id and str(ds_user_id).isdigit():
        loader.context.user_id = int(ds_user_id)

    log_info(
        logger,
        "Instagram cookie dosyasi oturuma yuklendi ve dogrulandi",
        stage="instagram.session",
        cookie_file=cookie_path,
        username=username,
        user_id=loader.context.user_id or "yok",
    )


def _build_instaloader(output_dir, cookie_path=None):
    os.makedirs(output_dir, exist_ok=True)
    log_info(logger, "Instaloader nesnesi kuruluyor", stage="instagram.session", output_dir=output_dir)
    loader = instaloader.Instaloader(
        quiet=True,
        dirname_pattern=output_dir,
        filename_pattern="{target}_{shortcode}",
        download_pictures=False,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
        max_connection_attempts=3,
        request_timeout=120.0,
        sanitize_paths=True,
    )
    _apply_instagram_cookiefile(loader, cookie_path)
    return loader


def _instagram_item_from_post(post, file_path):
    owner = sanitize_filename(getattr(post, "owner_username", None) or getattr(post.owner_profile, "username", "instagram"))
    caption = (getattr(post, "caption", None) or "").strip()
    return {
        "id": post.shortcode,
        "shortcode": post.shortcode,
        "video_id": post.shortcode,
        "title": caption.splitlines()[0][:120] if caption else f"{owner}_{post.shortcode}",
        "caption": caption,
        "uploader": owner,
        "platform": "instagram",
        "source_url": f"https://www.instagram.com/reel/{post.shortcode}/",
        "webpage_url": f"https://www.instagram.com/reel/{post.shortcode}/",
        "file_name": os.path.basename(file_path),
        "file_path": os.path.abspath(file_path),
        "downloaded_at": datetime.now().isoformat(),
        "taken_at": getattr(getattr(post, "date_utc", None), "isoformat", lambda: None)(),
        "like_count": getattr(post, "likes", None),
        "comment_count": getattr(post, "comments", None),
    }


def _is_reel_candidate(post):
    product_type = (getattr(post, "product_type", None) or "").lower()
    if product_type:
        return product_type == "clips"
    return bool(getattr(post, "is_video", False))


def _extract_audio_to_m4a(video_path, audio_path):
    ffmpeg_bin = get_ffmpeg_binary()
    commands = (
        [ffmpeg_bin, "-y", "-i", video_path, "-vn", "-c:a", "copy", audio_path],
        [ffmpeg_bin, "-y", "-i", video_path, "-vn", "-c:a", "aac", "-b:a", "192k", audio_path],
    )

    log_info(logger, "FFmpeg ile ses cikarma basladi", stage="ffmpeg.extract", ffmpeg_bin=ffmpeg_bin, video_path=video_path, audio_path=audio_path)
    last_error = None
    for index, command in enumerate(commands, start=1):
        log_info(logger, "FFmpeg komutu calistiriliyor", stage="ffmpeg.extract", attempt=index, command=" ".join(command))
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0 and os.path.isfile(audio_path):
            log_info(logger, "FFmpeg ile ses cikarma tamamlandi", stage="ffmpeg.extract", attempt=index, audio_path=audio_path)
            return audio_path

        if os.path.exists(audio_path):
            os.remove(audio_path)
        last_error = (result.stderr or result.stdout or "").strip()
        log_warning(logger, "FFmpeg denemesi basarisiz oldu", stage="ffmpeg.extract", attempt=index, error=last_error or result.returncode)

    raise RuntimeError(last_error or "ffmpeg ile ses cikarilamadi.")


class YtDlpProgressReporter:
    def __init__(self, download_stage, postprocess_stage):
        self.download_stage = download_stage
        self.postprocess_stage = postprocess_stage
        self._progress_buckets = {}

    def progress_hook(self, data):
        status = data.get("status")
        info_dict = data.get("info_dict") or {}
        video_id = info_dict.get("id") or data.get("filename") or "unknown"
        title = info_dict.get("title") or video_id

        if status == "downloading":
            percent = self._extract_percent(data)
            if percent is None:
                return
            bucket = min(10, max(0, int(percent // 10)))
            if self._progress_buckets.get(video_id) == bucket:
                return
            self._progress_buckets[video_id] = bucket
            log_info(
                logger,
                "yt-dlp indirme ilerliyor",
                stage=self.download_stage,
                video_id=video_id,
                title=title,
                progress=f"{percent:.1f}%",
            )
            return

        if status == "finished":
            log_info(
                logger,
                "yt-dlp ham indirme tamamlandi",
                stage=self.download_stage,
                video_id=video_id,
                title=title,
                temp_file=data.get("filename"),
            )

    def postprocessor_hook(self, data):
        if data.get("status") != "finished":
            return

        info_dict = data.get("info_dict") or {}
        video_id = info_dict.get("id") or "unknown"
        log_info(
            logger,
            "yt-dlp son isleme adimi tamamlandi",
            stage=self.postprocess_stage,
            video_id=video_id,
            title=info_dict.get("title") or video_id,
            final_path=info_dict.get("filepath"),
            postprocessor=data.get("postprocessor"),
        )

    @staticmethod
    def _extract_percent(data):
        downloaded = data.get("downloaded_bytes")
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        if downloaded and total:
            return round((downloaded / total) * 100, 1)

        text = (data.get("_percent_str") or "").strip().replace("%", "")
        try:
            return float(text)
        except ValueError:
            return None


class YtDlpMessageBridge:
    def __init__(self, stage):
        self.stage = stage

    def debug(self, message):
        text = (message or "").strip()
        if not text:
            return
        log_info(logger, "yt-dlp mesaj", stage=self.stage, detail=text)

    def warning(self, message):
        text = (message or "").strip()
        if not text:
            return
        log_warning(logger, "yt-dlp uyari", stage=self.stage, detail=text)

    def error(self, message):
        text = (message or "").strip()
        if not text:
            return
        log_warning(logger, "yt-dlp hata mesaji", stage=self.stage, detail=text)


def download_instagram_video(url, save_path="downloads", cookie_path=None):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)
    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        raise ValueError("Gecerli bir Instagram post veya reel URL girin.")

    log_info(logger, "Instagram tek video akisi basladi", stage="instagram.download", url=url, shortcode=shortcode, save_path=abs_save_path)
    loader = _build_instaloader(abs_save_path, cookie_path=cookie_path)
    post = instaloader.Post.from_shortcode(loader.context, shortcode)
    if not post.is_video:
        raise ValueError("Instagram gonderisi video icermiyor.")

    target = sanitize_filename(getattr(post, "owner_username", None) or post.owner_profile.username)
    video_path = _download_instaloader_post(loader, post, abs_save_path, target)
    if not video_path:
        raise FileNotFoundError("Instaloader video dosyasini indirmedi.")

    item = _instagram_item_from_post(post, video_path)
    log_info(logger, "Instagram tek video akisi tamamlandi", stage="instagram.download", shortcode=shortcode, file_path=video_path)
    return item


def download_instagram_profile_reels(url, save_path="downloads", cookie_path=None):
    username = extract_instagram_username(url)
    if not username:
        raise ValueError("Instagram hesap URL'si bekleniyor.")

    account_dir = os.path.abspath(os.path.join(save_path, sanitize_filename(username)))
    log_info(logger, "Instagram profil reels akisi basladi", stage="instagram.profile", url=url, username=username, account_dir=account_dir)
    loader = _build_instaloader(account_dir, cookie_path=cookie_path)
    try:
        profile = instaloader.Profile.from_username(loader.context, username)
    except instaloader.exceptions.ProfileNotExistsException:
        _raise_instagram_profile_lookup_error(username, cookie_path)

    posts = profile.get_reels() if hasattr(profile, "get_reels") else profile.get_posts()
    items = []
    for index, post in enumerate(posts, start=1):
        if not _is_reel_candidate(post):
            continue

        log_info(logger, "Instagram profilindeki reel indiriliyor", stage="instagram.profile", username=username, index=index, shortcode=post.shortcode)
        video_path = _download_instaloader_post(loader, post, account_dir, sanitize_filename(username))
        if not video_path:
            log_warning(logger, "Instagram reel indirme sonrasi dosya bulunamadi", stage="instagram.profile", username=username, shortcode=post.shortcode)
            continue
        items.append(_instagram_item_from_post(post, video_path))

    log_info(logger, "Instagram profil reels akisi tamamlandi", stage="instagram.profile", username=username, item_count=len(items))
    return {
        "platform": "instagram",
        "source_type": "profile_reels",
        "source_name": username,
        "source_url": f"https://www.instagram.com/{username}/",
        "download_dir": account_dir,
        "items": items,
    }


def download_instagram_audio(url, save_path="downloads", codec="m4a", cookie_path=None):
    abs_save_path = os.path.abspath(save_path)
    log_info(logger, "Instagram ses cikarma akisi basladi", stage="instagram.audio", url=url, codec=codec, save_path=abs_save_path)
    item = download_instagram_video(url, save_path=save_path, cookie_path=cookie_path)
    video_path = item["file_path"]
    stem = os.path.splitext(os.path.basename(video_path))[0]
    audio_path = build_unique_filepath(abs_save_path, stem, f".{codec}")
    _extract_audio_to_m4a(video_path, audio_path)

    try:
        os.remove(video_path)
        log_info(logger, "Gecici Instagram video dosyasi silindi", stage="instagram.audio", video_path=video_path)
    except OSError:
        log_warning(logger, "Gecici Instagram video dosyasi silinemedi", stage="instagram.audio", video_path=video_path)

    log_info(logger, "Instagram ses cikarma akisi tamamlandi", stage="instagram.audio", audio_path=audio_path)
    return audio_path


def convert_items_to_audio(items, codec="m4a"):
    converted_items = []
    for item in items or []:
        item_copy = dict(item)
        file_path = item_copy.get("file_path")
        if not file_path:
            converted_items.append(item_copy)
            continue

        abs_file_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_file_path):
            item_copy["file_path"] = abs_file_path
            item_copy["file_name"] = os.path.basename(abs_file_path)
            converted_items.append(item_copy)
            continue

        extension = os.path.splitext(abs_file_path)[1].lower()
        if extension == f".{codec.lower()}":
            item_copy["file_path"] = abs_file_path
            item_copy["file_name"] = os.path.basename(abs_file_path)
            converted_items.append(item_copy)
            continue

        stem = os.path.splitext(os.path.basename(abs_file_path))[0]
        audio_path = build_unique_filepath(os.path.dirname(abs_file_path), stem, f".{codec}")
        _extract_audio_to_m4a(abs_file_path, audio_path)

        try:
            os.remove(abs_file_path)
            log_info(logger, "Gecici video dosyasi silindi", stage="audio.batch", video_path=abs_file_path, audio_path=audio_path)
        except OSError:
            log_warning(logger, "Gecici video dosyasi silinemedi", stage="audio.batch", video_path=abs_file_path, audio_path=audio_path)

        item_copy["file_path"] = audio_path
        item_copy["file_name"] = os.path.basename(audio_path)
        converted_items.append(item_copy)

    return converted_items


def _build_ytdlp_video_options(abs_save_path, cookie_path=None, allow_playlist=False):
    ffmpeg_dir = get_ffmpeg_dir()
    downloaded_files = {}
    reporter = YtDlpProgressReporter("youtube.download", "youtube.postprocess")

    def remember_path(info_dict, filepath):
        if not info_dict or not filepath:
            return
        video_id = info_dict.get("id")
        if video_id:
            downloaded_files[video_id] = os.path.abspath(filepath)

    def progress_hook(data):
        reporter.progress_hook(data)
        if data.get("status") != "finished":
            return
        info_dict = data.get("info_dict") or {}
        remember_path(info_dict, data.get("filename"))

    def postprocessor_hook(data):
        reporter.postprocessor_hook(data)
        if data.get("status") != "finished":
            return
        info_dict = data.get("info_dict") or {}
        remember_path(info_dict, info_dict.get("filepath"))

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": YtDlpMessageBridge("youtube.engine"),
        "windowsfilenames": True,
        "cookiefile": cookie_path,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        },
        "ffmpeg_location": str(ffmpeg_dir) if ffmpeg_dir else "ffmpeg",
        "retries": 5,
        "fragment_retries": 5,
        "ignoreerrors": allow_playlist,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "paths": {"home": abs_save_path},
        "outtmpl": "%(title)s [%(id)s].%(ext)s",
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "noplaylist": not allow_playlist,
        "extractor_args": {
            "youtube": {"player_client": ["android", "ios", "web"]}
        },
    }

    log_info(
        logger,
        "yt-dlp video secenekleri hazirlandi",
        stage="youtube.prepare",
        save_path=abs_save_path,
        allow_playlist=allow_playlist,
        cookie_file=cookie_path or "yok",
        ffmpeg_location=ydl_opts["ffmpeg_location"],
    )
    return ydl_opts, downloaded_files


def _youtube_item_from_info(entry, downloaded_files, download_dir):
    if not entry:
        return None

    file_path = downloaded_files.get(entry.get("id"))
    if not file_path and entry.get("_filename"):
        file_path = os.path.abspath(entry["_filename"])
    if file_path and not os.path.isfile(file_path):
        file_path = None
    if not file_path and entry.get("id"):
        marker = f"[{entry.get('id')}]"
        for filename in os.listdir(download_dir):
            if marker in filename:
                candidate = os.path.join(download_dir, filename)
                if os.path.isfile(candidate):
                    file_path = os.path.abspath(candidate)
                    break

    item = {
        "id": entry.get("id"),
        "video_id": entry.get("id"),
        "title": entry.get("title") or entry.get("id"),
        "platform": "youtube",
        "uploader": entry.get("uploader") or entry.get("channel"),
        "source_url": entry.get("webpage_url") or entry.get("original_url") or entry.get("url"),
        "webpage_url": entry.get("webpage_url") or entry.get("original_url") or entry.get("url"),
        "duration": entry.get("duration"),
        "playlist_index": entry.get("playlist_index"),
        "file_name": os.path.basename(file_path) if file_path else None,
        "file_path": file_path,
        "downloaded_at": datetime.now().isoformat(),
    }
    log_info(
        logger,
        "YouTube oge metadatasi olusturuldu",
        stage="youtube.result",
        video_id=item["video_id"],
        title=item["title"],
        file_path=item["file_path"] or "bulunamadi",
    )
    return item


def download_youtube_video(url, save_path="downloads", cookie_path=None):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)
    log_info(logger, "YouTube tek video akisi basladi", stage="youtube.download", url=url, save_path=abs_save_path)
    ydl_opts, downloaded_files = _build_ytdlp_video_options(
        abs_save_path,
        cookie_path=cookie_path,
        allow_playlist=False,
    )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    item = _youtube_item_from_info(info, downloaded_files, abs_save_path)
    if not item or not item.get("video_id") or not item.get("file_path"):
        raise FileNotFoundError("YouTube videosu indirilemedi.")

    log_info(logger, "YouTube tek video akisi tamamlandi", stage="youtube.download", video_id=item["video_id"], file_path=item["file_path"])
    return item


def download_youtube_playlist(url, save_path="downloads", cookie_path=None):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)
    log_info(logger, "YouTube playlist akisi basladi", stage="youtube.playlist", url=url, save_path=abs_save_path)
    ydl_opts, downloaded_files = _build_ytdlp_video_options(
        abs_save_path,
        cookie_path=cookie_path,
        allow_playlist=True,
    )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    entries = info.get("entries") or []
    items = []
    for entry in entries:
        item = _youtube_item_from_info(entry, downloaded_files, abs_save_path)
        if item and item.get("video_id") and item.get("file_path"):
            items.append(item)

    log_info(
        logger,
        "YouTube playlist akisi tamamlandi",
        stage="youtube.playlist",
        playlist_id=info.get("id") or extract_youtube_playlist_id(url),
        title=info.get("title") or "-",
        item_count=len(items),
    )
    return {
        "platform": "youtube",
        "source_type": "playlist",
        "source_name": info.get("title") or info.get("id") or extract_youtube_playlist_id(url) or "playlist",
        "source_url": info.get("webpage_url") or url,
        "download_dir": abs_save_path,
        "playlist_id": info.get("id") or extract_youtube_playlist_id(url),
        "items": items,
    }


def download_audio_generic(url, save_path="downloads", codec="m4a", cookie_path=None):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)
    log_info(logger, "Genel ses indirme akisi basladi", stage="audio.generic", url=url, codec=codec, save_path=abs_save_path)

    if "instagram.com" in url:
        return download_instagram_audio(
            url,
            save_path=abs_save_path,
            codec=codec,
            cookie_path=resolve_cookie_file("instagram", cookie_path=cookie_path),
        )

    ffmpeg_dir = get_ffmpeg_dir()
    is_youtube = "youtube.com" in url or "youtu.be" in url
    final_file = []
    reporter = YtDlpProgressReporter("audio.download", "audio.postprocess")

    def postprocessor_hook(data):
        reporter.postprocessor_hook(data)
        if data["status"] == "finished" and data.get("info_dict", {}).get("filepath"):
            final_file.append(data["info_dict"]["filepath"])

    def progress_hook(data):
        reporter.progress_hook(data)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": YtDlpMessageBridge("audio.engine"),
        "windowsfilenames": True,
        "cookiefile": resolve_cookie_file("youtube", cookie_path=cookie_path),
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        },
        "ffmpeg_location": str(ffmpeg_dir) if ffmpeg_dir else "ffmpeg",
        "retries": 5,
        "fragment_retries": 5,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "paths": {"home": abs_save_path},
        "outtmpl": "%(title)s.%(ext)s",
        "noplaylist": True,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
    }

    if is_youtube:
        ydl_opts["extractor_args"] = {
            "youtube": {"player_client": ["android", "ios", "web"]}
        }

    log_info(
        logger,
        "Ses indirme ayarlari hazirlandi",
        stage="audio.generic",
        is_youtube=is_youtube,
        cookie_file=ydl_opts["cookiefile"] or "yok",
        ffmpeg_location=ydl_opts["ffmpeg_location"],
    )
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if final_file and os.path.isfile(final_file[-1]):
        downloaded_path = final_file[-1]
    else:
        ext = f".{codec}"
        audio_files = [
            os.path.join(abs_save_path, filename)
            for filename in os.listdir(abs_save_path)
            if filename.endswith(ext)
        ]
        if audio_files:
            downloaded_path = max(audio_files, key=os.path.getmtime)
        else:
            raise FileNotFoundError("Ses dosyasi bulunamadi.")

    title = info.get("title") or os.path.splitext(os.path.basename(downloaded_path))[0]
    extension = os.path.splitext(downloaded_path)[1] or f".{codec}"
    final_path = build_unique_filepath(abs_save_path, title, extension)

    if os.path.abspath(downloaded_path) != os.path.abspath(final_path):
        os.replace(downloaded_path, final_path)
        log_info(logger, "Ses dosyasi benzersiz isme tasindi", stage="audio.generic", source_path=downloaded_path, final_path=final_path)

    log_info(logger, "Genel ses indirme akisi tamamlandi", stage="audio.generic", title=title, final_path=final_path)
    return final_path
