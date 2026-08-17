import asyncio
import re
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request

from .base import SiteCrawlAdapter, _normalized_path, _notify_progress

class MetaInstagramPlatformAdapter(SiteCrawlAdapter):
    """Meta'nın render edilen Instagram Platform menüsündeki tüm rehberleri indirir."""

    name = "meta_instagram_platform"
    requires_interactive_collection = True
    documentation_root = "/documentation/instagram-platform"

    def matches(self, url):
        parsed = urlparse(url)
        path = _normalized_path(url)
        return (
            parsed.hostname == "developers.facebook.com"
            and (path == self.documentation_root or path.startswith(f"{self.documentation_root}/"))
        )

    async def collect_interactively(self, url, include_children, progress_callback=None):
        urls = [url]
        if include_children:
            urls = await self._rendered_menu_urls(url)
            if not urls:
                raise RuntimeError("Meta Instagram Platform sol menu rehberleri bulunamadi.")

        _notify_progress(
            progress_callback, "crawl_plan_ready", total_pages=len(urls), source=self.name
        )
        pages = await self._fetch_menu_markdown(urls, progress_callback)
        if len(pages) != len(urls):
            raise RuntimeError("Meta Instagram Platform rehberlerinin bir bolumu Markdown olarak alinamadi.")
        return pages

    @classmethod
    async def _fetch_menu_markdown(cls, urls, progress_callback):
        semaphore = asyncio.Semaphore(6)

        async def fetch(index, guide_url):
            async with semaphore:
                _notify_progress(
                    progress_callback, "page_started", current_page=index,
                    total_pages=len(urls), url=guide_url,
                )
                page = await asyncio.to_thread(cls._fetch_markdown, guide_url)
                _notify_progress(
                    progress_callback, "page_finished", current_page=index,
                    total_pages=len(urls), url=guide_url, saved=bool(page),
                )
                return page

        return [page for page in await asyncio.gather(
            *(fetch(index, guide_url) for index, guide_url in enumerate(urls, start=1))
        ) if page]

    @staticmethod
    def _fetch_markdown(url):
        """Meta'nın Markdown görünümü yalnızca curl kullanıcı aracısıyla Markdown döndürüyor."""
        # Paket girişindeki erişim noktası korunur; çağıranlar tek yerden
        # HTTP erişimini özelleştirebilir veya testte değiştirebilir.
        from . import urlopen

        markdown_url = quote(f"{url.rstrip('/')}.md", safe=":/?&=%")
        request = Request(markdown_url, headers={"User-Agent": "curl/8.0"})
        try:
            with urlopen(request, timeout=30) as response:
                content_type = (response.headers.get("Content-Type") or "").lower()
                content = response.read().decode("utf-8", errors="replace")
        except Exception:
            return ""
        if "markdown" not in content_type and not content.lstrip().startswith(("#", "---")):
            return ""
        return re.sub(r"\A---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL).strip()

    async def _rendered_menu_urls(self, current_url):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Meta adapter'i icin Playwright gerekli.") from exc

        menu_url = f"https://developers.facebook.com{self.documentation_root}"
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            try:
                await page.goto(menu_url, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_function(
                    f"""() => document.querySelectorAll(
                        'a[href^="{self.documentation_root}/"]'
                    ).length >= 80""",
                    timeout=90_000,
                )
                hrefs = await page.locator("a[href]").evaluate_all(
                    f"""nodes => nodes
                        .filter(node => {{
                            const href = node.getAttribute('href');
                            return href
                                && (href === '{self.documentation_root}'
                                    || href.startsWith('{self.documentation_root}/'))
                                && node.getBoundingClientRect().x < 400;
                        }})
                        .map(node => node.getAttribute('href'))"""
                )
                return self._menu_urls(hrefs, current_url)
            finally:
                await browser.close()

    @classmethod
    def _menu_urls(cls, hrefs, current_url):
        """Yalnızca sol menüdeki, aynı Instagram Platform ağacındaki URL'leri seçer."""
        urls = []
        seen = set()
        current_host = urlparse(current_url).netloc.lower()
        for href in hrefs:
            candidate = urljoin(current_url, href).split("#", 1)[0]
            parsed = urlparse(candidate)
            path = _normalized_path(candidate)
            if (
                parsed.netloc.lower() != current_host
                or (path != cls.documentation_root and not path.startswith(f"{cls.documentation_root}/"))
            ):
                continue
            if path.endswith(".md"):
                continue
            if candidate not in seen:
                seen.add(candidate)
                urls.append(candidate)
        return urls
