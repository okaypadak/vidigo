"""YouTube implementation; yt-dlp usage is isolated to this platform."""

import os

from .base import MediaPlatform
from utils.video_downloader import download_audio_generic, download_youtube_playlist, download_youtube_playlist_audio, download_youtube_video, list_youtube_video_urls, sanitize_directory_name
from utils.youtube_utils import extract_youtube_channel_name, extract_youtube_video_id, is_youtube_channel_url, is_youtube_playlist_url, is_youtube_url


class YouTubePlatform(MediaPlatform):
    name = "youtube"

    def classify(self, url):
        if not is_youtube_url(url):
            return None
        if is_youtube_playlist_url(url):
            source_type = "playlist"
        elif is_youtube_channel_url(url):
            source_type = "channel"
        elif extract_youtube_video_id(url):
            source_type = "video"
        else:
            raise ValueError("Gecerli bir YouTube video, playlist veya kanal URL'si girin.")
        return {"platform": self.name, "source_type": source_type, "url": url}

    def source_download_dir(self, platform_dir, source_type, url):
        if source_type == "channel":
            channel_name = extract_youtube_channel_name(url)
            if channel_name:
                path = os.path.join(platform_dir, sanitize_directory_name(channel_name))
                os.makedirs(path, exist_ok=True)
                return path
        return platform_dir

    def download(self, url, save_path, cookie_path=None, audio_only=False, item_callback=None):
        request = self.classify(url)
        if request["source_type"] in {"playlist", "channel"}:
            result = (
                download_youtube_playlist_audio(url, save_path=save_path, cookie_path=cookie_path, item_callback=item_callback)
                if audio_only
                else download_youtube_playlist(url, save_path=save_path, cookie_path=cookie_path)
            )
            result["source_type"] = request["source_type"]
            if request["source_type"] == "channel":
                result["source_name"] = extract_youtube_channel_name(url) or result.get("source_name")
            result["downloader"] = "yt-dlp+ffmpeg" if audio_only else "yt-dlp"
            return result

        item = download_youtube_video(url, save_path=save_path, cookie_path=cookie_path)
        return {"items": [item], "downloader": "yt-dlp"}

    def expand_source_items(self, url, cookie_path=None):
        request = self.classify(url)
        if request["source_type"] in {"playlist", "channel"}:
            return list_youtube_video_urls(url, cookie_path=cookie_path)
        return super().expand_source_items(url, cookie_path)

    def item_identifier(self, url):
        return extract_youtube_video_id(url)

    def converts_audio_during_download(self, source_type):
        return source_type in {"playlist", "channel"}

    def download_audio(self, url, save_path, cookie_path=None, codec="m4a"):
        return download_audio_generic(url, save_path=save_path, cookie_path=cookie_path, codec=codec, cookie_platform=self.name)
