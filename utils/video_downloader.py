import http.cookiejar
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import instaloader
import yt_dlp
from instaloader.nodeiterator import NodeIterator

from utils.app_logging import log_exception, log_info, log_warning
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
    os.makedirs(directory, exist_ok=True)
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


def strip_title_hashtags(title):
    text = re.sub(r"(?<!\w)#\S+", " ", str(title or ""))
    text = re.sub(r"\s+", " ", text).strip(" -_")
    return text


_strip_title_hashtags = strip_title_hashtags


def _youtube_js_runtime_options():
    node_path = shutil.which("node")
    if not node_path:
        return {}
    return {"js_runtimes": {"node": {"path": node_path}}}


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


def is_instagram_share_url(url):
    parsed = _parse_url(url)
    if not parsed:
        return False

    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]
    return "instagram.com" in host and len(parts) >= 2 and parts[0].lower() == "share"


def _instagram_request(url):
    return Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )


def _resolve_instagram_shared_url(url, cookie_path=None):
    if not is_instagram_share_url(url):
        return url

    cookie_jar = None
    if cookie_path and os.path.isfile(cookie_path):
        cookie_jar = http.cookiejar.MozillaCookieJar(cookie_path)
        cookie_jar.load(ignore_discard=True, ignore_expires=True)

    opener = build_opener(HTTPCookieProcessor(cookie_jar)) if cookie_jar else build_opener()
    with opener.open(_instagram_request(url), timeout=20) as response:
        return response.geturl() or url


def resolve_instagram_shortcode(url, cookie_path=None):
    shortcode = extract_instagram_shortcode(url)
    if shortcode:
        return shortcode

    if not is_instagram_share_url(url):
        return None

    try:
        resolved_url = _resolve_instagram_shared_url(url, cookie_path=cookie_path)
    except Exception:
        log_exception(logger, "Instagram paylasim linki cozumlenemedi", stage="instagram.resolve", url=url)
        return None

    shortcode = extract_instagram_shortcode(resolved_url)
    if shortcode:
        log_info(logger, "Instagram paylasim linki cozumlendi", stage="instagram.resolve", url=url, resolved_url=resolved_url, shortcode=shortcode)
    return shortcode


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
    if "instagram.com" not in host:
        return None

    if len(parts) == 1:
        username = parts[0].strip()
    elif len(parts) == 2 and parts[1].lower() == "reels":
        username = parts[0].strip()
    else:
        return None

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


def _uploader_download_dir(base_dir, uploader):
    safe_uploader = sanitize_filename(uploader)
    if not safe_uploader:
        return os.path.abspath(base_dir)

    abs_base_dir = os.path.abspath(base_dir)
    if os.path.basename(abs_base_dir).lower() == safe_uploader.lower():
        os.makedirs(abs_base_dir, exist_ok=True)
        return abs_base_dir

    path = os.path.join(abs_base_dir, safe_uploader)
    os.makedirs(path, exist_ok=True)
    return path


def _move_file_to_uploader_dir(file_path, base_dir, uploader):
    if not file_path or not uploader:
        return file_path

    abs_file_path = os.path.abspath(file_path)
    if not os.path.isfile(abs_file_path):
        return abs_file_path

    target_dir = _uploader_download_dir(base_dir, uploader)
    if os.path.abspath(os.path.dirname(abs_file_path)) == os.path.abspath(target_dir):
        return abs_file_path

    stem, extension = os.path.splitext(os.path.basename(abs_file_path))
    target_path = build_unique_filepath(target_dir, stem, extension)
    os.replace(abs_file_path, target_path)
    log_info(
        logger,
        "Dosya kanal klasorune tasindi",
        stage="download.organize",
        uploader=uploader,
        source_path=abs_file_path,
        target_path=target_path,
    )
    return target_path


def _move_item_file_to_uploader_dir(item, base_dir):
    uploader = item.get("uploader")
    file_path = item.get("file_path")
    moved_path = _move_file_to_uploader_dir(file_path, base_dir, uploader)
    if moved_path:
        item["file_path"] = moved_path
        item["file_name"] = os.path.basename(moved_path)
    return item


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


def _instagram_download_error_message(exc):
    text = str(exc)
    if "fbcdn.net" in text and ("Failed to establish a new connection" in text or "WinError 10051" in text):
        return (
            "Instaloader video dosyasini buldu ancak indirme baglantisini acamadi. "
            "Instagram mp4 dosyasina bu makineden 443 baglantisi kurulamiyor."
        )
    if "graphql/query" in text:
        return f"Instagram reels listesi alinamadi: {text}"
    return text


def _download_instaloader_post(loader, post, output_dir, target):
    existing_files = _iter_directory_files(output_dir)
    shortcode = getattr(post, "shortcode", None) or "instagram"

    expected_stem = f"{target}_{shortcode}"
    video_urls = list(getattr(post, "video_urls", None) or [])
    if video_urls:
        mtime = getattr(post, "date_local", None) or datetime.now()
        last_error = None
        for attempt, video_url in enumerate(video_urls, start=1):
            try:
                loader.download_pic(
                    filename=os.path.join(output_dir, expected_stem),
                    url=video_url,
                    mtime=mtime,
                )
                video_path = _find_latest_video_file(output_dir, stem=expected_stem, ignore_paths=existing_files) or _find_latest_video_file(
                    output_dir,
                    stem=expected_stem,
                )
                if video_path:
                    log_info(
                        logger,
                        "Indirildi",
                        stage="instagram.download.post",
                        shortcode=shortcode,
                        file_path=video_path,
                    )
                    return video_path
            except Exception as exc:
                last_error = exc
                error_text = _instagram_download_error_message(exc)
                continue

        if last_error:
            raise RuntimeError(_instagram_download_error_message(last_error))

    loader.download_post(post, target=target)

    video_path = _find_latest_video_file(output_dir, stem=expected_stem, ignore_paths=existing_files) or _find_latest_video_file(
        output_dir,
        stem=expected_stem,
    )
    if video_path:
        log_info(logger, "Indirildi", stage="instagram.download.post", shortcode=shortcode, file_path=video_path)
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

    if not cookie_map.get("sessionid"):
        raise ValueError(
            "Instagram cookie dosyasinda sessionid bulunamadi. "
            "~/cookie/instagram.txt dosyasini yenileyin."
        )

    ds_user_id = cookie_map.get("ds_user_id")
    if ds_user_id and str(ds_user_id).isdigit():
        loader.context.user_id = int(ds_user_id)

    log_info(
        logger,
        "Instagram cookie dosyasi oturuma yuklendi",
        stage="instagram.session",
        cookie_file=cookie_path,
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
        max_connection_attempts=1,
        request_timeout=30.0,
        sanitize_paths=True,
    )
    loader.context.error = lambda *args, **kwargs: None
    _apply_instagram_cookiefile(loader, cookie_path)
    return loader


def _instagram_item_from_post(post, file_path):
    owner_profile = getattr(post, "owner_profile", None)
    owner = sanitize_filename(getattr(post, "owner_username", None) or getattr(owner_profile, "username", "instagram"))
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


def _extract_instagram_reels_edges(data):
    if not isinstance(data, dict):
        raise RuntimeError("Instagram reels listesi alinamadi: GraphQL bos yanit dondu.")

    connection = (data.get("data") or {}).get("xdt_api__v1__clips__user__connection_v2")
    if not isinstance(connection, dict):
        errors = data.get("errors") or []
        if errors:
            message = errors[0].get("message") if isinstance(errors[0], dict) else str(errors[0])
            raise RuntimeError(f"Instagram reels listesi alinamadi: {message}")
        raise RuntimeError("Instagram reels listesi alinamadi: GraphQL reels verisi bos dondu.")

    return connection


class InstagramReelListItem:
    def __init__(self, media, username):
        self._media = media or {}
        self.shortcode = self._media.get("code") or self._media.get("shortcode") or self._media.get("pk")
        self.owner_username = username
        self.product_type = "clips"
        self.is_video = self._media.get("media_type") == 2 or bool(self._media.get("video_versions"))
        self.video_urls = self._extract_video_urls(self._media)
        self.caption = self._extract_caption(self._media)
        self.likes = self._media.get("like_count")
        self.comments = self._media.get("comment_count")
        self.date_utc = self._extract_date(self._media)

    @property
    def date_local(self):
        if self.date_utc:
            return self.date_utc.astimezone()
        return datetime.now()

    @staticmethod
    def _extract_video_urls(media):
        urls = []
        for version in media.get("video_versions") or []:
            url = version.get("url")
            if url and url not in urls:
                urls.append(url)
        return urls

    @staticmethod
    def _extract_caption(media):
        caption = media.get("caption")
        if isinstance(caption, dict):
            return caption.get("text") or ""
        return caption or ""

    @staticmethod
    def _extract_date(media):
        timestamp = media.get("taken_at") or media.get("taken_at_ts")
        if not timestamp:
            return None
        try:
            return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError, OSError):
            return None


def _instagram_reel_item_from_node(node, username):
    media = (node or {}).get("media") or node or {}
    return InstagramReelListItem(media, username)


def _instagram_profile_reels_iterator(loader, profile, username):
    user_id = getattr(profile, "userid", None)
    if user_id:
        return NodeIterator(
            context=loader.context,
            edge_extractor=_extract_instagram_reels_edges,
            node_wrapper=lambda node: _instagram_reel_item_from_node(node, username),
            query_variables={
                "data": {
                    "page_size": 12,
                    "include_feed_video": True,
                    "target_user_id": str(user_id),
                }
            },
            query_referer=f"https://www.instagram.com/{username}/",
            is_first=instaloader.Profile._make_is_newest_checker(),
            doc_id="7845543455542541",
            query_hash=None,
        )

    return profile.get_reels() if hasattr(profile, "get_reels") else profile.get_posts()


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

        if status == "finished":
            log_info(
                logger,
                "indirme tamamlandi",
                stage=self.download_stage,
                video_id=video_id,
                title=title,
            )

    def postprocessor_hook(self, data):
        if data.get("status") != "finished":
            return
        if data.get("postprocessor") not in ("MoveFiles", "FFmpegExtractAudio"):
            return

        info_dict = data.get("info_dict") or {}
        video_id = info_dict.get("id") or "unknown"
        log_info(
            logger,
            "isleme tamamlandi",
            stage=self.postprocess_stage,
            video_id=video_id,
            title=info_dict.get("title") or video_id,
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
        pass

    def warning(self, message):
        text = (message or "").strip()
        if not text:
            return
        _NOISY_WARNINGS = ("GVS PO Token", "SABR streaming", "impersonation", "impersonate")
        if any(w in text for w in _NOISY_WARNINGS):
            return
        log_warning(logger, "yt-dlp uyari", stage=self.stage, detail=text)

    def error(self, message):
        text = (message or "").strip()
        if not text:
            return
        _NOISY_ERRORS = ("Requested format is not available", "No video formats found", "is no longer supported")
        if any(msg in text for msg in _NOISY_ERRORS):
            return
        log_warning(logger, "yt-dlp hata", stage=self.stage, detail=text)


def download_instagram_video(url, save_path="downloads", cookie_path=None):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)
    shortcode = resolve_instagram_shortcode(url, cookie_path=cookie_path)
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
    item = _move_item_file_to_uploader_dir(item, abs_save_path)
    log_info(logger, "Instagram tek video akisi tamamlandi", stage="instagram.download", shortcode=shortcode, file_path=item["file_path"])
    return item


def download_instagram_profile_reels(url, save_path="downloads", cookie_path=None, audio_only=False, item_callback=None):
    username = extract_instagram_username(url)
    if not username:
        raise ValueError("Instagram hesap URL'si bekleniyor.")

    base_save_path = os.path.abspath(save_path)
    safe_username = sanitize_filename(username)
    if os.path.basename(base_save_path) == safe_username:
        account_dir = base_save_path
    else:
        account_dir = os.path.abspath(os.path.join(base_save_path, safe_username))
    log_info(logger, "Instagram profil reels akisi basladi", stage="instagram.profile", url=url, username=username, account_dir=account_dir)
    loader = _build_instaloader(account_dir, cookie_path=cookie_path)
    try:
        profile = instaloader.Profile.from_username(loader.context, username)
    except instaloader.exceptions.ProfileNotExistsException:
        _raise_instagram_profile_lookup_error(username, cookie_path)

    items = []
    errors = []
    index = 0
    try:
        posts = _instagram_profile_reels_iterator(loader, profile, username)
        post_iterator = iter(posts)
    except Exception as exc:
        error_text = _instagram_download_error_message(exc)
        errors.append(
            {
                "stage": "iterate",
                "error": error_text,
            }
        )
        log_warning(
            logger,
            "Instagram reels listesi okunurken hata olustu",
            stage="instagram.profile",
            username=username,
            error=error_text,
        )
        post_iterator = iter(())
    while True:
        try:
            post = next(post_iterator)
        except StopIteration:
            break
        except Exception as exc:
            error_text = str(exc)
            errors.append(
                {
                    "stage": "iterate",
                    "error": error_text,
                }
            )
            log_warning(
                logger,
                "Instagram reels listesi okunurken hata olustu",
                stage="instagram.profile",
                username=username,
                error=error_text,
            )
            break

        index += 1
        if not _is_reel_candidate(post):
            continue

        shortcode = getattr(post, "shortcode", None) or f"index-{index}"
        try:
            video_path = _download_instaloader_post(loader, post, account_dir, sanitize_filename(username))
            if not video_path:
                error_text = "Instaloader video dosyasini indirmedi."
                if not items:
                    raise RuntimeError(
                        "Instagram reel listesi alindi ancak hicbir video indirilemedi. "
                        f"Ilk hata ({shortcode}): {error_text}"
                    )
                log_warning(
                    logger,
                    "Instagram reel indirme sonrasi dosya bulunamadi",
                    stage="instagram.profile",
                    username=username,
                    shortcode=shortcode,
                )
                errors.append(
                    {
                        "shortcode": shortcode,
                        "stage": "download",
                        "error": error_text,
                    }
                )
                continue

            if audio_only:
                stem = os.path.splitext(os.path.basename(video_path))[0]
                audio_path = build_unique_filepath(os.path.dirname(video_path), stem, ".m4a")
                _extract_audio_to_m4a(video_path, audio_path)
                try:
                    os.remove(video_path)
                    log_info(logger, "Gecici video dosyasi silindi", stage="instagram.profile", video_path=video_path)
                except OSError:
                    log_warning(logger, "Gecici video dosyasi silinemedi", stage="instagram.profile", video_path=video_path)
                item = _instagram_item_from_post(post, audio_path)
            else:
                item = _instagram_item_from_post(post, video_path)

            items.append(item)
            if item_callback:
                item_callback(
                    item,
                    platform="instagram",
                    source_type="profile_reels",
                    source_name=username,
                    source_url=f"https://www.instagram.com/{username}/",
                    download_dir=account_dir,
                    downloader="instaloader",
                )
        except Exception as exc:
            error_text = _instagram_download_error_message(exc)
            errors.append(
                {
                    "shortcode": shortcode,
                    "stage": "item",
                    "error": error_text,
                }
            )
            log_warning(
                logger,
                "Instagram reel indirilemedi",
                stage="instagram.profile",
                username=username,
                index=index,
                shortcode=shortcode,
                error=error_text,
            )
            if not items:
                raise RuntimeError(
                    "Instagram reel listesi alindi ancak hicbir video indirilemedi. "
                    f"Ilk hata ({shortcode}): {error_text}"
                )
            continue

    log_info(
        logger,
        "Instagram profil reels akisi tamamlandi",
        stage="instagram.profile",
        username=username,
        item_count=len(items),
        failed_count=len(errors),
    )
    if not items and errors:
        first_error = errors[0]
        shortcode = first_error.get("shortcode") or "bilinmiyor"
        error_text = first_error.get("error") or "Bilinmeyen indirme hatasi."
        raise RuntimeError(
            "Instagram reel listesi alindi ancak hicbir video indirilemedi. "
            f"Ilk hata ({shortcode}): {error_text}"
        )
    if not items:
        raise FileNotFoundError(
            "Instagram profilinde indirilebilir reel bulunamadi veya Instagram reels listesi bos dondu."
        )

    result = {
        "platform": "instagram",
        "source_type": "profile_reels",
        "source_name": username,
        "source_url": f"https://www.instagram.com/{username}/",
        "download_dir": account_dir,
        "items": items,
    }
    if errors:
        result["errors"] = errors
        result["failed_count"] = len(errors)
    return result


def download_instagram_audio(url, save_path="downloads", codec="m4a", cookie_path=None):
    abs_save_path = os.path.abspath(save_path)
    log_info(logger, "Instagram ses cikarma akisi basladi", stage="instagram.audio", url=url, codec=codec, save_path=abs_save_path)
    item = download_instagram_video(url, save_path=save_path, cookie_path=cookie_path)
    video_path = item["file_path"]
    stem = os.path.splitext(os.path.basename(video_path))[0]
    audio_path = build_unique_filepath(os.path.dirname(video_path), stem, f".{codec}")
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
            "youtube": {"player_client": ["web"]}
        },
    }
    ydl_opts.update(_youtube_js_runtime_options())

    return ydl_opts, downloaded_files


def _build_ytdlp_audio_playlist_options(abs_save_path, cookie_path=None, item_callback=None):
    ffmpeg_dir = get_ffmpeg_dir()
    downloaded_files = {}
    notified_ids = set()
    reporter = YtDlpProgressReporter("youtube.audio.download", "youtube.audio.postprocess")

    def remember_path(info_dict, filepath):
        if not info_dict or not filepath:
            return
        video_id = info_dict.get("id")
        if video_id:
            downloaded_files[video_id] = os.path.abspath(filepath)

    def notify_item(info_dict, filepath):
        if not item_callback or not info_dict or not filepath or not os.path.isfile(filepath):
            return
        video_id = info_dict.get("id")
        if video_id in notified_ids:
            return
        item = _youtube_item_from_info(info_dict, downloaded_files, abs_save_path)
        if item and item.get("file_path"):
            if video_id:
                notified_ids.add(video_id)
            item_callback(item)

    def progress_hook(data):
        reporter.progress_hook(data)
        if data.get("status") != "finished":
            return
        info_dict = data.get("info_dict") or {}
        filepath = data.get("filename")
        remember_path(info_dict, filepath)
        if filepath and os.path.splitext(filepath)[1].lower() == ".m4a":
            notify_item(info_dict, filepath)

    def postprocessor_hook(data):
        reporter.postprocessor_hook(data)
        if data.get("status") != "finished":
            return
        info_dict = data.get("info_dict") or {}
        filepath = info_dict.get("filepath") or data.get("filepath")
        remember_path(info_dict, filepath)
        notify_item(info_dict, downloaded_files.get(info_dict.get("id")) or filepath)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": YtDlpMessageBridge("youtube.audio.engine"),
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
        "ignoreerrors": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "paths": {"home": abs_save_path},
        "outtmpl": "%(title)s [%(id)s].%(ext)s",
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "0",
            }
        ],
        "noplaylist": False,
        "extractor_args": {
            "youtube": {"player_client": ["web"]}
        },
    }
    ydl_opts.update(_youtube_js_runtime_options())

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
        for root, _, filenames in os.walk(download_dir):
            for filename in filenames:
                if marker not in filename:
                    continue
                candidate = os.path.join(root, filename)
                if os.path.isfile(candidate):
                    file_path = os.path.abspath(candidate)
                    break
            if file_path:
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
    item = _move_item_file_to_uploader_dir(item, download_dir)
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


def download_youtube_playlist_audio(url, save_path="downloads", cookie_path=None, item_callback=None):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)
    log_info(logger, "YouTube playlist ses akisi basladi", stage="youtube.audio.playlist", url=url, save_path=abs_save_path)
    ydl_opts, downloaded_files = _build_ytdlp_audio_playlist_options(
        abs_save_path,
        cookie_path=cookie_path,
        item_callback=item_callback,
    )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    entries = info.get("entries") or []
    items = []
    seen = set()
    for entry in entries:
        item = _youtube_item_from_info(entry, downloaded_files, abs_save_path)
        if not item or not item.get("video_id") or not item.get("file_path"):
            continue
        if item["video_id"] in seen:
            continue
        seen.add(item["video_id"])
        items.append(item)

    log_info(
        logger,
        "YouTube playlist ses akisi tamamlandi",
        stage="youtube.audio.playlist",
        playlist_id=info.get("id") or extract_youtube_playlist_id(url),
        title=info.get("title") or "-",
        item_count=len(items),
    )
    return {
        "platform": "youtube",
        "source_type": "playlist",
        "source_name": info.get("channel") or info.get("uploader") or info.get("title") or info.get("id") or extract_youtube_playlist_id(url) or "playlist",
        "source_url": info.get("webpage_url") or url,
        "download_dir": abs_save_path,
        "playlist_id": info.get("id") or extract_youtube_playlist_id(url),
        "items": items,
    }


def _is_valid_video_id(video_id):
    return bool(video_id) and len(video_id) == 11 and not video_id.startswith("UC")


def _flatten_entries(entries, uploader_fallback=None):
    """entries içindeki iç içe playlist yapısını düzleştirir, gerçek video ID'lerini döndürür."""
    items = []
    seen = set()
    for entry in (entries or []):
        if not entry:
            continue
        # İç içe playlist (tab, kanal vb.) ise entries'ini de tara
        sub_entries = entry.get("entries")
        if sub_entries:
            items.extend(_flatten_entries(sub_entries, uploader_fallback=uploader_fallback))
            continue
        video_id = entry.get("id")
        if not _is_valid_video_id(video_id):
            continue
        item_url = f"https://www.youtube.com/watch?v={video_id}"
        if item_url in seen:
            continue
        seen.add(item_url)
        items.append({
            "url": item_url,
            "video_id": video_id,
            "title": entry.get("title"),
            "uploader": entry.get("uploader") or entry.get("channel") or uploader_fallback,
        })
    return items


def _channel_base_url(url):
    """Kanal URL'sinden tab kısmını temizler, temel URL'yi döner."""
    stripped = url.rstrip("/")
    for tab in ("/videos", "/shorts", "/streams", "/live", "/playlists", "/community"):
        if stripped.endswith(tab):
            return stripped[: -len(tab)]
    return stripped


def _fetch_youtube_tab(tab_url, ydl_opts):
    log_info(logger, "YouTube tab listesi aliniyor", stage="youtube.list", url=tab_url)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tab_url, download=False)
        return info if isinstance(info, dict) else None
    except Exception:
        log_exception(logger, "YouTube tab listesi alinamadi", stage="youtube.list", url=tab_url)
        return None


def list_youtube_video_urls(url, cookie_path=None):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": YtDlpMessageBridge("youtube.list.engine"),
        "cookiefile": cookie_path,
        "extract_flat": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": False,
        "extractor_args": {
            "youtube": {"player_client": ["web"]}
        },
    }
    ydl_opts.update(_youtube_js_runtime_options())

    playlist_id = extract_youtube_playlist_id(url)
    if playlist_id:
        info = _fetch_youtube_tab(url, ydl_opts)
        if not info:
            return []

        uploader = info.get("uploader") or info.get("channel")
        if _is_valid_video_id(info.get("id")):
            webpage_url = info.get("webpage_url") or f"https://www.youtube.com/watch?v={info['id']}"
            return [{"url": webpage_url, "video_id": info["id"], "title": info.get("title"), "uploader": uploader}]

        items = _flatten_entries(info.get("entries") or [], uploader_fallback=uploader)
        log_info(logger, "YouTube playlist video listesi alindi", stage="youtube.list", url=url, playlist_id=playlist_id, item_count=len(items))
        return items

    # Tek video URL'si mi?
    parsed = _parse_url(url)
    if parsed and "youtube.com/watch" in url or "youtu.be/" in url:
        info = _fetch_youtube_tab(url, ydl_opts)
        if info and _is_valid_video_id(info.get("id")):
            uploader = info.get("uploader") or info.get("channel")
            webpage_url = info.get("webpage_url") or f"https://www.youtube.com/watch?v={info['id']}"
            return [{"url": webpage_url, "video_id": info["id"], "title": info.get("title"), "uploader": uploader}]
        return []

    base_url = _channel_base_url(url)
    stripped = url.rstrip("/")
    if stripped.endswith("/shorts"):
        tabs_to_fetch = [base_url + "/shorts"]
    elif stripped.endswith("/videos"):
        tabs_to_fetch = [base_url + "/videos"]
    else:
        tabs_to_fetch = [base_url + "/videos", base_url + "/shorts"]

    seen = set()
    all_items = []
    uploader = None

    for tab_url in tabs_to_fetch:
        info = _fetch_youtube_tab(tab_url, ydl_opts)
        if not info:
            continue

        if not uploader:
            uploader = info.get("uploader") or info.get("channel")

        if _is_valid_video_id(info.get("id")):
            video_id = info["id"]
            if video_id not in seen:
                seen.add(video_id)
                webpage_url = info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"
                all_items.append({"url": webpage_url, "video_id": video_id, "title": info.get("title"), "uploader": uploader})
            continue

        entries = info.get("entries") or []
        for item in _flatten_entries(entries, uploader_fallback=uploader):
            if item["video_id"] not in seen:
                seen.add(item["video_id"])
                all_items.append(item)

        log_info(logger, "YouTube tab islendi", stage="youtube.list", url=tab_url, new_items=len(all_items))

    log_info(logger, "YouTube kaynak video listesi alindi", stage="youtube.list", url=url, item_count=len(all_items))
    return all_items


def fetch_channel_catalog(url, cookie_path=None):
    """Kanal URL'si için videos ve shorts listelerini ayrı ayrı döner."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": YtDlpMessageBridge("youtube.catalog.engine"),
        "cookiefile": cookie_path,
        "extract_flat": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": False,
        "extractor_args": {
            "youtube": {"player_client": ["web"]}
        },
    }
    ydl_opts.update(_youtube_js_runtime_options())

    base_url = _channel_base_url(url)
    uploader = None

    def fetch_tab(tab_url):
        nonlocal uploader
        info = _fetch_youtube_tab(tab_url, ydl_opts)
        if not info:
            return []
        if not uploader:
            uploader = info.get("uploader") or info.get("channel")
        entries = info.get("entries") or []
        return _flatten_entries(entries, uploader_fallback=uploader)

    videos = fetch_tab(base_url + "/videos")
    shorts = fetch_tab(base_url + "/shorts")

    log_info(
        logger,
        "YouTube kanal katalogu alindi",
        stage="youtube.catalog",
        url=url,
        video_count=len(videos),
        short_count=len(shorts),
    )
    return {
        "channel": uploader,
        "url": url,
        "fetched_at": datetime.now().isoformat(),
        "video_count": len(videos),
        "short_count": len(shorts),
        "videos": videos,
        "shorts": shorts,
    }


def save_channel_catalog(url, save_dir, cookie_path=None):
    """Kanal kataloğunu save_dir/catalog.json olarak kaydeder."""
    catalog = fetch_channel_catalog(url, cookie_path=cookie_path)
    os.makedirs(save_dir, exist_ok=True)
    catalog_path = os.path.join(save_dir, "catalog.json")
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    log_info(logger, "Kanal katalogu kaydedildi", stage="youtube.catalog", path=catalog_path)
    return catalog_path


def download_audio_generic(url, save_path="downloads", codec="m4a", cookie_path=None):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)
    existing_files = _iter_directory_files(abs_save_path)
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
        "cookiefile": resolve_cookie_file("youtube", cookie_path=cookie_path) if is_youtube else resolve_cookie_file("youtube", cookie_path=cookie_path),
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
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": "0",
            }
        ],
    }

    if is_youtube:
        ydl_opts["extractor_args"] = {
            "youtube": {"player_client": ["web"]}
        }
        ydl_opts.update(_youtube_js_runtime_options())

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    final_candidates = [path for path in final_file if path and os.path.isfile(path)]
    final_candidates = [path for path in final_candidates if os.path.splitext(path)[1].lower() == f".{codec.lower()}"]
    if final_candidates:
        downloaded_path = final_candidates[-1]
    else:
        ext = f".{codec}"
        audio_files = [
            os.path.join(root, filename)
            for root, _, filenames in os.walk(abs_save_path)
            for filename in filenames
            if filename.lower().endswith(ext.lower()) and os.path.join(root, filename) not in existing_files
        ]
        if audio_files:
            downloaded_path = max(audio_files, key=os.path.getmtime)
        else:
            raise FileNotFoundError("Ses dosyasi bulunamadi.")

    title = info.get("title") or os.path.splitext(os.path.basename(downloaded_path))[0]
    extension = os.path.splitext(downloaded_path)[1] or f".{codec}"
    uploader = info.get("uploader") or info.get("channel")
    target_dir = _uploader_download_dir(abs_save_path, uploader) if uploader else abs_save_path
    final_path = build_unique_filepath(target_dir, title, extension)

    if os.path.abspath(downloaded_path) != os.path.abspath(final_path):
        os.replace(downloaded_path, final_path)
        log_info(logger, "Ses dosyasi benzersiz isme tasindi", stage="audio.generic", source_path=downloaded_path, final_path=final_path)

    log_info(logger, "Genel ses indirme akisi tamamlandi", stage="audio.generic", title=title, final_path=final_path)
    return final_path


def _vtt_to_txt(vtt_path):
    """VTT altyazı dosyasını düz metne çevirir, VTT dosyasını siler."""
    with open(vtt_path, encoding="utf-8") as f:
        raw = f.read()

    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:") or line.startswith("X-TIMESTAMP-MAP"):
            continue
        if re.match(r"^\d+:\d{2}:\d{2}[.,]\d{3}\s*-->\s*", line):
            continue
        if re.match(r"^\d+$", line):
            continue
        # Inline cue timestamps ve HTML tag'lerini temizle
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line:
            continue
        lines.append(line)

    # Ardışık tekrar eden satırları kaldır
    deduped = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)

    txt_path = re.sub(r"\.[a-z]{2,3}\.vtt$", ".txt", vtt_path)
    if txt_path == vtt_path:
        txt_path = os.path.splitext(vtt_path)[0] + ".txt"

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(deduped))

    os.remove(vtt_path)
    return txt_path


def _find_vtt_files(directory, existing_files=None):
    existing_files = {os.path.abspath(path) for path in (existing_files or set())}
    result = []
    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            if not filename.lower().endswith(".vtt"):
                continue
            path = os.path.abspath(os.path.join(root, filename))
            if path not in existing_files:
                result.append(path)
    return result


def _clean_youtube_transcript_title(entry, txt_path):
    title = entry.get("title") if isinstance(entry, dict) else None
    if not title:
        title = os.path.splitext(os.path.basename(txt_path))[0]
        title = re.sub(r"\s*\[[^\]]+\]\s*$", "", title)
    title = _strip_title_hashtags(title)
    return title or os.path.splitext(os.path.basename(txt_path))[0]


def _rename_youtube_transcript_txt(txt_path, entry):
    title = _clean_youtube_transcript_title(entry, txt_path)
    target_path = build_unique_filepath(os.path.dirname(txt_path), title, ".txt")
    if os.path.abspath(target_path) != os.path.abspath(txt_path):
        os.replace(txt_path, target_path)
    return target_path


def _youtube_transcript_item_from_info(entry, txt_path, source_url):
    video_id = entry.get("id") if isinstance(entry, dict) else None
    title = _clean_youtube_transcript_title(entry, txt_path)
    with open(txt_path, encoding="utf-8") as f:
        text = f.read()
    return {
        "id": video_id,
        "video_id": video_id,
        "title": title,
        "platform": "youtube",
        "uploader": entry.get("uploader") or entry.get("channel") if isinstance(entry, dict) else None,
        "source_url": entry.get("webpage_url") or entry.get("original_url") or source_url if isinstance(entry, dict) else source_url,
        "webpage_url": entry.get("webpage_url") or entry.get("original_url") or source_url if isinstance(entry, dict) else source_url,
        "file_name": os.path.basename(txt_path),
        "file_path": txt_path,
        "txt_path": txt_path,
        "downloaded_at": datetime.now().isoformat(),
        "engine": "ytdlp_subtitle",
        "transcript": text,
    }


def _youtube_caption_language_candidates(info):
    if not isinstance(info, dict):
        return ["tr"]

    captions = info.get("automatic_captions") or info.get("subtitles") or {}
    languages = [language for language, variants in captions.items() if variants]
    preferred = []
    default_language = info.get("language")

    if default_language:
        original_variant = f"{default_language}-orig"
        if original_variant in languages:
            preferred.append(original_variant)
        if default_language in languages:
            preferred.append(default_language)

    if "tr-orig" in languages:
        preferred.append("tr-orig")
    if "tr" in languages:
        preferred.append("tr")

    preferred.extend(languages)

    result = []
    for language in preferred or ["tr"]:
        if language and language not in result:
            result.append(language)
    return result


def download_youtube_transcript_ytdlp(url, save_path, cookie_path=None):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)
    ffmpeg_dir = get_ffmpeg_dir()
    existing_vtt_files = _find_vtt_files(abs_save_path)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": YtDlpMessageBridge("youtube.transcript"),
        "windowsfilenames": True,
        "cookiefile": cookie_path,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        },
        "ffmpeg_location": str(ffmpeg_dir) if ffmpeg_dir else "ffmpeg",
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitlesformat": "vtt",
        "paths": {"home": abs_save_path, "subtitle": abs_save_path},
        "outtmpl": "%(title)s [%(id)s].%(ext)s",
        "ignoreerrors": True,
        "noplaylist": False,
        "extractor_args": {
            "youtube": {"player_client": ["web"]}
        },
    }
    opts.update(_youtube_js_runtime_options())

    log_info(
        logger,
        "yt-dlp altyazi indirme basladi",
        stage="youtube.transcript",
        url=url,
        save_path=abs_save_path,
        cookie_file=cookie_path or "yok",
    )

    with yt_dlp.YoutubeDL(opts) as ydl:
        metadata = ydl.extract_info(url, download=False)

    info = None
    new_vtt_files = []
    for language in _youtube_caption_language_candidates(metadata):
        download_opts = dict(opts)
        download_opts["subtitleslangs"] = [language]
        with yt_dlp.YoutubeDL(download_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        new_vtt_files = _find_vtt_files(abs_save_path, existing_files=existing_vtt_files)
        if new_vtt_files:
            break

    if not new_vtt_files:
        log_warning(logger, "yt-dlp altyazi dosyasi uretilmedi, atlaniyor", stage="youtube.transcript", url=url)
        return []

    entries = []
    if isinstance(info, dict) and info.get("entries"):
        entries = [entry for entry in info.get("entries") or [] if entry]
    elif isinstance(info, dict):
        entries = [info]

    items = []
    for index, vtt_path in enumerate(new_vtt_files):
        try:
            txt_path = _vtt_to_txt(vtt_path)
            entry = entries[index] if index < len(entries) else {}
            txt_path = _rename_youtube_transcript_txt(txt_path, entry)
            item = _youtube_transcript_item_from_info(entry, txt_path, url)
            items.append(item)
            log_info(logger, "VTT metin dosyasina donusturuldu", stage="youtube.transcript", txt_path=txt_path)
        except Exception:
            log_exception(logger, "VTT donusturme basarisiz", stage="youtube.transcript", vtt_path=vtt_path)

    log_info(logger, "yt-dlp altyazi indirme tamamlandi", stage="youtube.transcript", url=url, item_count=len(items))
    return items
