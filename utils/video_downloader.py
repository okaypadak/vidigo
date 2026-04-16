import os
import yt_dlp
from utils.ffmpeg_utils import get_ffmpeg_dir


def sanitize_filename(name):
    return ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in name).replace(' ', '_')


def download_audio_generic(url, save_path="downloads", codec="mp3"):
    os.makedirs(save_path, exist_ok=True)

    ffmpeg_dir = get_ffmpeg_dir()
    is_instagram = "instagram.com" in url
    if is_instagram:
        cookie_path = os.path.expanduser("~/cookie/instagram.com.txt")
        if not os.path.isfile(cookie_path):
            cookie_path = None  # cookie yoksa cookie'siz dene
    else:
        cookie_path = None

    is_youtube = "youtube.com" in url or "youtu.be" in url
    is_instagram = "instagram.com" in url

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "cookiefile": cookie_path,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0.0.0 Safari/537.36"
        },
        "ffmpeg_location": str(ffmpeg_dir) if ffmpeg_dir else "ffmpeg",
        "retries": 5,
        "fragment_retries": 5,
    }

    if is_youtube:
        # YouTube sık sık varsayılan web client formatlarına 403 döndürüyor.
        # android/ios client'ları genelde geçerli stream URL'i veriyor.
        ydl_opts["extractor_args"] = {
            "youtube": {"player_client": ["android", "ios", "web"]}
        }

    if is_instagram:
        ydl_opts["http_headers"]["Referer"] = "https://www.instagram.com/"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = sanitize_filename(info.get("title", "video"))
        uploader = sanitize_filename(info.get("uploader", "channel"))

    filename = f"{uploader}-{title}.%(ext)s"
    full_path = os.path.join(save_path, filename)

    ydl_opts.update({
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": full_path,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": codec,
            "preferredquality": "192",
        }],
        "noplaylist": True,
    })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    ext = f".{codec}"
    for file in os.listdir(save_path):
        if file.endswith(ext) and file.startswith(f"{uploader}-{title}"):
            return os.path.join(save_path, file)

    raise FileNotFoundError("Ses dosyasi bulunamadi.")
