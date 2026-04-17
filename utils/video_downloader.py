import os
import re
import yt_dlp
from utils.ffmpeg_utils import get_ffmpeg_dir


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


def download_audio_generic(url, save_path="downloads", codec="m4a"):
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)

    ffmpeg_dir = get_ffmpeg_dir()
    is_youtube = "youtube.com" in url or "youtu.be" in url
    is_instagram = "instagram.com" in url

    cookie_path = None
    if is_instagram:
        cookie_path = os.path.expanduser("~/cookie/instagram.com.txt")
        if not os.path.isfile(cookie_path):
            raise FileNotFoundError(
                "Instagram cookie dosyası bulunamadı: ~/cookie/instagram.com.txt"
            )

    final_file = []

    def postprocessor_hook(d):
        if d["status"] == "finished" and d.get("info_dict", {}).get("filepath"):
            final_file.append(d["info_dict"]["filepath"])

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
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

    if is_instagram:
        ydl_opts["http_headers"]["Referer"] = "https://www.instagram.com/"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if final_file and os.path.isfile(final_file[-1]):
        downloaded_path = final_file[-1]
    else:
        ext = f".{codec}"
        audio_files = [
            os.path.join(abs_save_path, f)
            for f in os.listdir(abs_save_path)
            if f.endswith(ext)
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
