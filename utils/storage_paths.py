"""TextForge tarafindan kalici olarak yazilan dosyalarin ortak konumu."""

import os


def _media_root():
    """Varsayilan olarak kullanicinin TextForge klasorunun mutlak yolunu dondurur."""
    configured_path = os.environ.get("TEXTFORGE_MEDIA_ROOT", "").strip()
    if configured_path:
        return os.path.abspath(os.path.expanduser(configured_path))
    return os.path.join(os.path.expanduser("~"), "textforge")


def _state_root():
    """Keep application metadata outside the user-visible media library."""
    configured_path = os.environ.get("TEXTFORGE_STATE_ROOT", "").strip()
    if configured_path:
        return os.path.abspath(os.path.expanduser(configured_path))
    return os.path.join(os.path.dirname(_media_root()), ".textforge")


# Windows'ta varsayilan medya kok: C:\\Users\\<kullanici>\\textforge
# Uygulama kayitlari: C:\\Users\\<kullanici>\\.textforge
MEDIA_ROOT = _media_root()
STATE_ROOT = _state_root()
DOWNLOAD_ROOT = os.path.join(STATE_ROOT, "downloads")
TRANSCRIPTS_ROOT = os.path.join(STATE_ROOT, "transcripts")
