"""Platform-specific media operations behind a small, extensible contract."""

from abc import ABC, abstractmethod


class MediaPlatform(ABC):
    """Contract for a supported media host.

    Implement this class and register it in ``registry.py`` when adding a new
    host (for example X.com).  Platform download libraries remain confined to
    their own implementation.
    """

    name: str

    @abstractmethod
    def classify(self, url):
        """Return a request dictionary for *url*, or ``None`` when it is not ours."""

    @abstractmethod
    def source_download_dir(self, platform_dir, source_type, url):
        """Return the directory used for this source."""

    @abstractmethod
    def download(self, url, save_path, cookie_path=None, audio_only=False, item_callback=None):
        """Download a classified source and return the common result payload."""

    def expand_source_items(self, url, cookie_path=None):
        """Return individual items for a multi-item source."""
        return [{"url": url}]

    def converts_audio_during_download(self, source_type):
        """Whether this source already produces audio when ``audio_only`` is set."""
        return False

    @abstractmethod
    def download_audio(self, url, save_path, cookie_path=None, codec="m4a"):
        """Download a single post's audio in the requested codec."""

    @abstractmethod
    def item_identifier(self, url):
        """Return the stable identifier used for duplicate detection."""
