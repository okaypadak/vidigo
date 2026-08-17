"""Siteye özgü doküman erişim stratejileri.

Her adapter yalnızca bağlantı keşfi ve içeriğe erişim biçiminden sorumludur.
Markdown temizleme ve dosyaya yazma genel tarama akışında kalır.
"""

import asyncio
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class CrawlAccessPlan:
    name: str
    urls: list[str]
    use_native_markdown: bool = False


class SiteCrawlAdapter:
    name = "generic"
    requires_interactive_collection = False

    def matches(self, url):
        return False

    def discover(self, url, html, include_children):
        return None

    async def collect_interactively(self, url, include_children, progress_callback=None):
        return []


def _normalized_path(url):
    return unicodedata.normalize("NFC", unquote(urlparse(url).path)).rstrip("/") or "/"




def _notify_progress(progress_callback, event, **fields):
    if progress_callback is None:
        return
    try:
        progress_callback(event, **fields)
    except Exception:
        pass
