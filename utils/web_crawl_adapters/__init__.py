"""Siteye özgü doküman erişim stratejileri.

Her adapter kendi modülünde bulunur; bu paket yalnızca ortak API ve kaydı sağlar.
"""

import asyncio
import re
from urllib.parse import quote
from urllib.request import Request, urlopen

from .base import CrawlAccessPlan, SiteCrawlAdapter, _notify_progress
from .trendyol import TrendyolDocumentationAdapter
from .ideasoft import IdeasoftStoplightAdapter
from .meta_instagram import MetaInstagramPlatformAdapter
from .hepsiburada import HepsiburadaPortalAdapter
from .ikas import IkasDeveloperPortalAdapter

SITE_CRAWL_ADAPTERS = [
    TrendyolDocumentationAdapter(),
    IdeasoftStoplightAdapter(),
    MetaInstagramPlatformAdapter(),
    HepsiburadaPortalAdapter(),
    IkasDeveloperPortalAdapter(),
]


def resolve_site_adapter(url):
    return next((adapter for adapter in SITE_CRAWL_ADAPTERS if adapter.matches(url)), None)


def _fetch_native_markdown(url):
    markdown_url = quote(f"{url.rstrip('/')}.md", safe=":/?&=%")
    request = Request(markdown_url, headers={"User-Agent": "TextForge Markdown Downloader/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            content = response.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    if "markdown" not in content_type and not content.lstrip().startswith(("#", "---")):
        return ""
    content = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL)
    return re.sub(r"^Fetch the complete documentation index at:.*$", "", content, flags=re.MULTILINE).strip()


async def fetch_access_plan(plan, progress_callback=None):
    if not plan.use_native_markdown:
        return []

    semaphore = asyncio.Semaphore(6)

    async def fetch(index, url):
        async with semaphore:
            _notify_progress(progress_callback, "page_started", current_page=index, total_pages=len(plan.urls), url=url)
            page = await asyncio.to_thread(_fetch_native_markdown, url)
            _notify_progress(progress_callback, "page_finished", current_page=index, total_pages=len(plan.urls), url=url, saved=bool(page))
            return page

    return [page for page in await asyncio.gather(*(fetch(index, url) for index, url in enumerate(plan.urls, start=1))) if page]
