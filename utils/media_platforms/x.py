"""X.com single-post implementation.

X has no playlist/profile expansion yet.  yt-dlp is used only by this adapter,
so its X-specific options and cookies cannot affect YouTube or Instagram.
"""

import os
from urllib.parse import urlparse

import yt_dlp

from .base import MediaPlatform
from utils.ffmpeg_utils import get_ytdlp_ffmpeg_location
from utils.video_downloader import YtDlpMessageBridge, YtDlpProgressReporter, download_audio_generic


def _x_status_id(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    try:
        status_index = parts.index("status")
        return parts[status_index + 1] if len(parts) > status_index + 1 else None
    except ValueError:
        return None


class XPlatform(MediaPlatform):
    name = "x"

    def classify(self, url):
        status_id = _x_status_id(url)
        if status_id:
            return {"platform": self.name, "source_type": "post", "url": url}
        parsed = urlparse(url)
        if parsed.netloc.lower().split(":", 1)[0] in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}:
            raise ValueError("X icin video iceren bir post URL'si girin (…/status/<id>).")
        return None

    def source_download_dir(self, platform_dir, source_type, url):
        return platform_dir

    def download(self, url, save_path, cookie_path=None, audio_only=False, item_callback=None):
        os.makedirs(save_path, exist_ok=True)
        files = []
        reporter = YtDlpProgressReporter("x.download", "x.postprocess")

        def progress_hook(data):
            reporter.progress_hook(data)
            if data.get("status") == "finished" and data.get("filename"):
                files.append(os.path.abspath(data["filename"]))

        ffmpeg_location = get_ytdlp_ffmpeg_location()
        options = {
            "quiet": True, "no_warnings": True, "logger": YtDlpMessageBridge("x.engine"),
            "windowsfilenames": True, "cookiefile": cookie_path,
            "ffmpeg_location": ffmpeg_location,
            "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
            "merge_output_format": "mp4", "paths": {"home": os.path.abspath(save_path)},
            "outtmpl": "%(title)s [%(id)s].%(ext)s", "noplaylist": True,
            "progress_hooks": [progress_hook], "retries": 5, "fragment_retries": 5,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
        path = next((path for path in reversed(files) if os.path.isfile(path)), None)
        if not path:
            marker = f"[{info.get('id')}]"
            path = next((os.path.join(root, file) for root, _, names in os.walk(save_path) for file in names if marker in file), None)
        if not path or not os.path.isfile(path):
            raise FileNotFoundError("X videosu indirilemedi.")
        return {"items": [{"id": info.get("id"), "video_id": info.get("id"), "title": info.get("title") or info.get("id"), "platform": self.name, "uploader": info.get("uploader") or info.get("channel"), "source_url": url, "webpage_url": info.get("webpage_url") or url, "file_name": os.path.basename(path), "file_path": path}], "downloader": "yt-dlp"}

    def item_identifier(self, url):
        return _x_status_id(url)

    def download_audio(self, url, save_path, cookie_path=None, codec="m4a"):
        return download_audio_generic(url, save_path=save_path, cookie_path=cookie_path, codec=codec, cookie_platform=self.name)
