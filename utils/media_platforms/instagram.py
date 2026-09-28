"""Instagram implementation backed exclusively by Instagrapi."""

import os

from .base import MediaPlatform
from utils.video_downloader import download_instagram_audio, download_instagram_profile_reels, download_instagram_video, extract_instagram_shortcode, extract_instagram_username, is_instagram_share_url, is_instagram_url, sanitize_directory_name


class InstagramPlatform(MediaPlatform):
    name = "instagram"

    def classify(self, url):
        if not is_instagram_url(url):
            return None
        if extract_instagram_shortcode(url) or is_instagram_share_url(url):
            source_type = "reel"
        elif extract_instagram_username(url):
            source_type = "profile_reels"
        else:
            raise ValueError("Instagram icin hesap URL'si veya reel URL'si girin.")
        return {"platform": self.name, "source_type": source_type, "url": url}

    def source_download_dir(self, platform_dir, source_type, url):
        if source_type == "profile_reels":
            username = extract_instagram_username(url)
            if username:
                path = os.path.join(platform_dir, sanitize_directory_name(username))
                os.makedirs(path, exist_ok=True)
                return path
        return platform_dir

    def download(self, url, save_path, cookie_path=None, audio_only=False, item_callback=None):
        request = self.classify(url)
        if request["source_type"] == "profile_reels":
            result = download_instagram_profile_reels(
                url,
                save_path=save_path,
                cookie_path=cookie_path,
                audio_only=audio_only,
                item_callback=item_callback,
            )
            return result
        item = download_instagram_video(url, save_path=save_path, cookie_path=cookie_path)
        return {"items": [item], "downloader": "instagrapi"}

    def item_identifier(self, url):
        return extract_instagram_shortcode(url)

    def download_audio(self, url, save_path, cookie_path=None, codec="m4a"):
        return download_instagram_audio(url, save_path=save_path, cookie_path=cookie_path, codec=codec)
