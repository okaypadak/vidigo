"""ikas Developer Portal (Docusaurus) dokumantasyon erisimi."""

from urllib.parse import urljoin, urlparse

from .base import SiteCrawlAdapter, _normalized_path, _notify_progress


class IkasDeveloperPortalAdapter(SiteCrawlAdapter):
    """ikas API Docs sol menusundeki tum yaprak sayfalari toplar.

    Docusaurus menusu ilk yuklemede kapali kategoriler halinde geldigi icin,
    statik HTML'den baglanti okumak API Reference sayfalarinin neredeyse
    tamamini atlar. Bu adapter once render edilmis agaci acar, sonra yalnizca
    API Docs alanindaki yaprak URL'leri ziyaret eder.
    """

    name = "ikas_developer_portal"
    requires_interactive_collection = True
    documentation_root = "/docs"
    max_menu_expansions = 1_000

    def matches(self, url):
        parsed = urlparse(url)
        path = _normalized_path(url)
        return (
            parsed.hostname in {"ikas.dev", "ikas.com"}
            and (path == "/docs/intro" or path.startswith("/docs/api/"))
        )

    async def collect_interactively(self, url, include_children, progress_callback=None):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("ikas adapter'i icin Playwright gerekli.") from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1440, "height": 1000})
            page = await context.new_page()
            try:
                # Bir alt sayfadan baslandiginda bile ayni API Docs agacini
                # eksiksiz okumak icin menunun giris dugumunu yukleriz.
                menu_url = self._menu_url(url)
                await page.goto(menu_url, wait_until="domcontentloaded", timeout=60_000)
                await page.locator("aside.docSidebarContainer").wait_for(
                    state="visible", timeout=30_000
                )
                urls = [url]
                if include_children:
                    await self._expand_all_menu_groups(page)
                    hrefs = await page.locator("aside.docSidebarContainer a[href]").evaluate_all(
                        "nodes => nodes.map(node => node.getAttribute('href'))"
                    )
                    urls = self._menu_urls(hrefs, menu_url)
                    if not urls:
                        raise RuntimeError("ikas API Docs sol menu yapraklari bulunamadi.")

                total_pages = len(urls)
                _notify_progress(
                    progress_callback, "crawl_plan_ready", total_pages=total_pages, source=self.name
                )
                pages = []
                for index, page_url in enumerate(urls, start=1):
                    _notify_progress(
                        progress_callback, "page_started", current_page=index,
                        total_pages=total_pages, url=page_url,
                    )
                    content = ""
                    try:
                        await page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
                        content = await self._page_markdown(page)
                    except Exception as exc:
                        error = str(exc)
                    else:
                        error = None
                    if content:
                        pages.append(content)
                    _notify_progress(
                        progress_callback, "page_finished", current_page=index,
                        total_pages=total_pages, url=page_url, saved=bool(content),
                        skipped=not bool(content), error=error,
                    )
                if len(pages) != total_pages:
                    raise RuntimeError("ikas API Docs sayfalarinin bir bolumu alinamadi.")
                return pages
            finally:
                await context.close()
                await browser.close()

    @classmethod
    async def _expand_all_menu_groups(cls, page):
        """Docusaurus'taki her kapali kategori yeni dallar kalmayana dek acar."""
        for _ in range(cls.max_menu_expansions):
            groups = page.locator(
                "aside.docSidebarContainer "
                "li.theme-doc-sidebar-item-category.menu__list-item--collapsed "
                "> a.menu__link--sublist"
            )
            if not await groups.count():
                return
            await groups.first.click()
            await page.wait_for_timeout(75)
        raise RuntimeError("ikas sol menu 1000 acilir dal sinirina ulasti.")

    @classmethod
    def _menu_urls(cls, hrefs, current_url):
        """API Docs sol menusundeki baglantilari sirayla tekillestirir."""
        current = urlparse(current_url)
        urls = []
        seen = set()
        for href in hrefs:
            candidate = urljoin(current_url, href or "").split("#", 1)[0]
            parsed = urlparse(candidate)
            path = _normalized_path(candidate)
            if (
                parsed.netloc.lower() != current.netloc.lower()
                or (path != "/docs/intro" and not path.startswith("/docs/api/"))
            ):
                continue
            key = candidate.rstrip("/")
            if key not in seen:
                seen.add(key)
                urls.append(candidate)
        return urls

    @staticmethod
    def _menu_url(url):
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/docs/intro"

    @staticmethod
    async def _page_markdown(page):
        article = page.locator("main article")
        await article.wait_for(state="visible", timeout=30_000)
        content = (await article.inner_text()).strip()
        title = (await article.locator("h1").first.inner_text()).strip()
        if not content:
            return ""
        if title:
            content = content.removeprefix(title).lstrip()
            return f"# {title}\n\n{content}".strip()
        return content
