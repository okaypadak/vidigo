"""TextForge tarafindan kalici olarak yazilan dosyalarin ortak konumu."""

import os


def _media_root():
    """Varsayilan olarak kullanicinin TextForge klasorunun mutlak yolunu dondurur."""
    configured_path = os.environ.get("TEXTFORGE_MEDIA_ROOT", "").strip()
    if configured_path:
        return os.path.abspath(os.path.expanduser(configured_path))
    return os.path.join(os.path.expanduser("~"), "textforge")


# Windows'ta varsayilan: C:\\Users\\<kullanici>\\textforge
MEDIA_ROOT = _media_root()
DOWNLOAD_ROOT = os.path.join(MEDIA_ROOT, "downloads")
TRANSCRIPTS_ROOT = os.path.join(MEDIA_ROOT, "transcripts")
