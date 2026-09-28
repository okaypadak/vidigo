"""Supported media platform registry."""

from .instagram import InstagramPlatform
from .youtube import YouTubePlatform
from .x import XPlatform

_PLATFORMS = {}


def register_media_platform(platform):
    """Register a platform implementation.

    Adding X.com only requires a new ``MediaPlatform`` implementation and one
    registration call; the download service itself does not need a new branch.
    """
    if not getattr(platform, "name", None):
        raise ValueError("Medya platformunun bir adi olmali.")
    _PLATFORMS[platform.name] = platform


register_media_platform(YouTubePlatform())
register_media_platform(InstagramPlatform())
register_media_platform(XPlatform())


def classify_media_url(url):
    """Classify a supported URL without exposing platform-specific checks."""
    for platform in _PLATFORMS.values():
        result = platform.classify(url)
        if result:
            return result
    names = ", ".join(platform.name.title() for platform in _PLATFORMS.values())
    raise ValueError(f"Su anda sadece {names} URL'leri destekleniyor.")


def get_media_platform(name):
    try:
        return _PLATFORMS[name]
    except KeyError as exc:
        raise ValueError(f"Desteklenmeyen medya platformu: {name}") from exc
