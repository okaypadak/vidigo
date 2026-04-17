import os
import re
import subprocess
from urllib.parse import urlparse

import instaloader
import yt_dlp

from utils.ffmpeg_utils import get_ffmpeg_binary, get_ffmpeg_dir


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
    if not url:
        return None

    if "://" not in url:
        url = "https://" + url

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]

    if "instagram.com" not in host or len(parts) < 2:
        return None

    if parts[0] in ("p", "reel", "reels", "tv"):
        return parts[1]

    return None


def _extract_audio_to_m4a(video_path, audio_path):
    ffmpeg_bin = get_ffmpeg_binary()
    commands = (
        [ffmpeg_bin, "-y", "-i", video_path, "-vn", "-c:a", "copy", audio_path],
        [ffmpeg_bin, "-y", "-i", video_path, "-vn", "-c:a", "aac", "-b:a", "192k", audio_path],
    )

    last_error = None
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0 and os.path.isfile(audio_path):
            return audio_path

        if os.path.exists(audio_path):
            os.remove(audio_path)
        last_error = (result.stderr or result.stdout or "").strip()

    raise RuntimeError(last_error or "ffmpeg ile ses cikarilamadi.")


def download_instagram_audio(url, save_path="downloads", codec="m4a"):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)

    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        raise ValueError("Gecerli bir Instagram post veya reel URL girin.")

    loader = instaloader.Instaloader(
        quiet=True,
        dirname_pattern=abs_save_path,
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

    post = instaloader.Post.from_shortcode(loader.context, shortcode)
    if not post.is_video:
        raise ValueError("Instagram gonderisi video icermiyor.")

    target = sanitize_filename(getattr(post, "owner_username", None) or post.owner_profile.username)
    stem = f"{target}_{post.shortcode}"
    existing_files = {
        os.path.join(abs_save_path, filename)
        for filename in os.listdir(abs_save_path)
    }

    loader.download_post(post, target=target)

    video_candidates = []
    for filename in os.listdir(abs_save_path):
        path = os.path.join(abs_save_path, filename)
        if path in existing_files:
            continue
        if os.path.splitext(filename)[0] == stem and os.path.splitext(filename)[1].lower() in {".mp4", ".mov", ".webm", ".mkv"}:
            video_candidates.append(path)

    if not video_candidates:
        for filename in os.listdir(abs_save_path):
            path = os.path.join(abs_save_path, filename)
            if os.path.splitext(filename)[0] == stem and os.path.splitext(filename)[1].lower() in {".mp4", ".mov", ".webm", ".mkv"}:
                video_candidates.append(path)

    if not video_candidates:
        raise FileNotFoundError("Instaloader video dosyasini indirmedi.")

    video_path = max(video_candidates, key=os.path.getmtime)
    audio_path = build_unique_filepath(abs_save_path, stem, f".{codec}")
    _extract_audio_to_m4a(video_path, audio_path)

    try:
        os.remove(video_path)
    except OSError:
        pass

    return audio_path


def download_audio_generic(url, save_path="downloads", codec="m4a"):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)

    if "instagram.com" in url:
        return download_instagram_audio(url, save_path=abs_save_path, codec=codec)

    ffmpeg_dir = get_ffmpeg_dir()
    is_youtube = "youtube.com" in url or "youtu.be" in url
    final_file = []

    def postprocessor_hook(data):
        if data["status"] == "finished" and data.get("info_dict", {}).get("filepath"):
            final_file.append(data["info_dict"]["filepath"])

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "windowsfilenames": True,
        "cookiefile": None,
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
        "postprocessor_hooks": [postprocessor_hook],
    }

    if is_youtube:
        ydl_opts["extractor_args"] = {
            "youtube": {"player_client": ["android", "ios", "web"]}
        }

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

    return final_path
