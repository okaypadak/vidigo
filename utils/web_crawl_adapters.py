"""Siteye özgü doküman erişim stratejileri.

Her adapter yalnızca bağlantı keşfi ve içeriğe erişim biçiminden sorumludur.
Markdown temizleme ve dosyaya yazma genel tarama akışında kalır.
"""

import asyncio
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen


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


class TrendyolDocumentationAdapter(SiteCrawlAdapter):
    """Trendyol'un ReadMe tabanlı sol menüsündeki aktif doküman grubunu indirir."""

    name = "trendyol_readme"

    def matches(self, url):
        return urlparse(url).hostname == "developers.trendyol.com"

    def discover(self, url, html, include_children):
        if not include_children:
            return None
        urls = self._active_sidebar_group_urls(html, url)
        if len(urls) <= 1:
            return None
        return CrawlAccessPlan(name=self.name, urls=urls, use_native_markdown=True)

    @staticmethod
    def _active_sidebar_group_urls(html, current_url):
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html or "", "html.parser")
        current_path = _normalized_path(current_url)
        active_link = next(
            (
                anchor for anchor in soup.find_all("a", href=True)
                if _normalized_path(urljoin(current_url, anchor["href"])) == current_path
                and "active" in (anchor.get("class") or [])
            ),
            None,
        )
        if active_link is None:
            return []

        group = active_link.find_parent("ul", class_=lambda value: value and "subpages" in value)
        if group is None:
            return []

        urls = []
        seen = set()
        current_host = urlparse(current_url).netloc.lower()
        for anchor in group.find_all("a", href=True):
            candidate = urljoin(current_url, anchor["href"]).split("#", 1)[0]
            parsed = urlparse(candidate)
            if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != current_host:
                continue
            key = candidate.rstrip("/")
            if key not in seen:
                seen.add(key)
                urls.append(candidate)
        return urls


class IdeasoftStoplightAdapter(SiteCrawlAdapter):
    """IdeaSoft Stoplight menüsündeki her yaprak rehberi tarayıcıda toplar."""

    name = "ideasoft_stoplight"
    requires_interactive_collection = True
    stoplight_project_id = "cHJqOjIzODAzMw"

    def matches(self, url):
        parsed = urlparse(url)
        return parsed.hostname == "apidoc.ideasoft.dev" and _normalized_path(url).startswith("/docs/")

    async def collect_interactively(self, url, include_children, progress_callback=None):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Ideasoft adapter'i icin Playwright gerekli.") from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            try:
                urls = [url]
                if include_children:
                    # Stoplight menüsü sanallaştırılmış olabildiği için yalnızca
                    # ekranda o anda bulunan bağlantıları okumak eksik sonuç verir.
                    # Render edilmiş ağacı açıyoruz; eksiksiz sayfa planını ise aynı
                    # ağacın Stoplight TOC verisinden alıyoruz.
                    await self._collect_page(page, url)
                    expanded_groups = await self._expand_all_menu_groups(page)
                    rendered_urls = await self._rendered_menu_urls(page, url)
                    try:
                        table_of_contents = await asyncio.to_thread(self._fetch_table_of_contents)
                    except Exception as exc:
                        raise RuntimeError(
                            "Ideasoft tam sol menu agaci Stoplight'tan alinamadi; "
                            "eksik sayfa kaydetmemek icin tarama durduruldu."
                        ) from exc
                    toc_urls = self._menu_leaf_urls(table_of_contents, url)
                    if not toc_urls:
                        raise RuntimeError("Ideasoft sol menu rehberleri bulunamadi.")
                    _notify_progress(
                        progress_callback, "crawl_menu_expanded",
                        expanded_groups=expanded_groups, source=self.name,
                    )
                    urls = self._merge_menu_urls(url, toc_urls, rendered_urls)

                pages = []
                total_pages = len(urls)
                _notify_progress(
                    progress_callback, "crawl_plan_ready", total_pages=total_pages, source=self.name
                )
                for index, guide_url in enumerate(urls, start=1):
                    _notify_progress(
                        progress_callback, "page_started", current_page=index,
                        total_pages=total_pages, url=guide_url,
                    )
                    content = await self._collect_page(page, guide_url)
                    if content:
                        pages.append(content)
                    _notify_progress(
                        progress_callback, "page_finished", current_page=index,
                        total_pages=total_pages, url=guide_url, saved=bool(content),
                    )
                return pages
            finally:
                await browser.close()

    @staticmethod
    async def _expand_all_menu_groups(page):
        """Sol menüdeki kapalı accordion dallarını, yeni dal kalmayana kadar açar."""
        expanded_groups = 0
        for _ in range(500):
            buttons = page.locator("button[aria-expanded='false']")
            target = None
            for index in range(await buttons.count()):
                button = buttons.nth(index)
                box = await button.bounding_box()
                # Stoplight sol menüsü dar sol kolonda bulunur; üst araç çubuğu
                # ve sayfa içindeki accordion'lar tarama ağacına dahil edilmez.
                if box and box["x"] < 500:
                    target = button
                    break
            if target is None:
                return expanded_groups
            await target.click()
            expanded_groups += 1
            await page.wait_for_timeout(75)
        raise RuntimeError("Ideasoft sol menü 500 açılır dal sınırına ulaştı.")

    @staticmethod
    async def _rendered_menu_urls(page, current_url):
        """Açılmış Stoplight sol menüsünde görünen yaprak doküman URL'lerini döndürür."""
        hrefs = await page.locator("a[href]").evaluate_all(
            """nodes => nodes
                .filter(node => {
                    const box = node.getBoundingClientRect();
                    return box.width > 0 && box.height > 0 && box.x < 500;
                })
                .map(node => node.getAttribute('href'))"""
        )
        return IdeasoftStoplightAdapter._menu_urls(hrefs, current_url)

    @staticmethod
    def _menu_urls(hrefs, current_url):
        """Aynı IdeaSoft doküman ağacındaki görünür yaprak bağlantılarını tekilleştirir."""
        parsed = urlparse(current_url)
        path_parts = [part for part in _normalized_path(current_url).split("/") if part]
        if len(path_parts) < 2 or path_parts[0] != "docs":
            return []
        documentation_root = f"/docs/{path_parts[1]}"
        urls = []
        seen = set()
        for href in hrefs:
            candidate = urljoin(current_url, href).split("#", 1)[0]
            candidate_parsed = urlparse(candidate)
            path = _normalized_path(candidate)
            if (
                candidate_parsed.netloc.lower() != parsed.netloc.lower()
                or (path != documentation_root and not path.startswith(f"{documentation_root}/"))
            ):
                continue
            if candidate not in seen:
                seen.add(candidate)
                urls.append(candidate)
        return urls

    @staticmethod
    def _merge_menu_urls(current_url, *url_groups):
        """Açılış sayfası ve tüm menü kaynaklarını sıralarını koruyarak birleştirir."""
        urls = []
        seen = set()
        for candidate in (current_url, *(url for group in url_groups for url in group)):
            key = candidate.split("#", 1)[0].rstrip("/")
            if key not in seen:
                seen.add(key)
                urls.append(candidate)
        return urls

    @classmethod
    def _menu_leaf_urls(cls, table_of_contents, current_url):
        """Stoplight'ın sol menüsünü oluşturan TOC verisindeki yaprak URL'leri döndürür."""
        parsed = urlparse(current_url)
        path_parts = [part for part in _normalized_path(current_url).split("/") if part]
        if len(path_parts) < 2 or path_parts[0] != "docs":
            return []
        docs_root = f"{parsed.scheme}://{parsed.netloc}/docs/{path_parts[1]}"
        urls = []
        stack = list(reversed((table_of_contents or {}).get("items", [])))
        while stack:
            item = stack.pop()
            children = item.get("items", [])
            stack.extend(reversed(children))
            slug = item.get("slug")
            # Bazı Stoplight TOC düğümlerinin kalıcı id alanı yoktur; slug yine
            # geçerli bir rehber adresidir ve atlanmamalıdır.
            if slug:
                urls.append(f"{docs_root}/{quote(str(slug), safe='-._~')}")
        return urls

    @classmethod
    def _fetch_table_of_contents(cls):
        endpoint = (
            f"https://stoplight.io/api/v1/projects/{cls.stoplight_project_id}"
            "/table-of-contents?branch=main"
        )
        request = Request(endpoint, headers={"User-Agent": "Vidigo Markdown Downloader/1.0"})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    async def _collect_page(page, url):
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        # Stoplight önce kabuğu, ardından endpoint şeması ve örneklerini istemci
        # tarafında getirir. Sadece DOMContentLoaded sonrasında okumak, uzun
        # sayfalarda eksik içerik kaydedilmesine yol açabiliyor.
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            # Analytics veya erişilebilirlik betikleri ağı açık tuttuğunda ana
            # içerik ölçütü aşağıdaki beklemede yine doğrulanır.
            pass
        main = page.locator("main")
        await main.wait_for(state="visible", timeout=30_000)
        await page.wait_for_function(
            """() => {
                const main = document.querySelector('main');
                return main && main.innerText.trim().length > 100;
            }""",
            timeout=30_000,
        )
        return await IdeasoftStoplightAdapter._wait_for_stable_main_content(page, main)

    @staticmethod
    async def _wait_for_stable_main_content(page, main, timeout_ms=12_000, interval_ms=500):
        """Geç yüklenen Stoplight içeriği iki ardışık okumada sabitlenene kadar bekler."""
        elapsed_ms = 0
        previous = ""
        while elapsed_ms < timeout_ms:
            current = (await main.inner_text()).strip()
            if current and current == previous:
                return current
            previous = current
            await page.wait_for_timeout(interval_ms)
            elapsed_ms += interval_ms
        return previous


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


class HepsiburadaPortalAdapter(SiteCrawlAdapter):
    """CAPTCHA sonrasinda gorunur tarayicidan Hepsiburada rehberlerini toplar."""

    name = "hepsiburada_portal"
    requires_interactive_collection = True
    max_pages = 100
    _CONTENT_READY_SCRIPT = """() => {
        const main = document.querySelector('main');
        const heading = main && main.querySelector('h1');
        return heading
            && main.innerText.trim().length > 80
            && !main.innerText.includes('Guide yükleniyor');
    }"""

    def matches(self, url):
        return urlparse(url).hostname == "developers.hepsiburada.com"

    async def collect_interactively(self, url, include_children, progress_callback=None):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Hepsiburada adapter'i icin Playwright gerekli.") from exc

        profile_dir = os.path.join(os.path.expanduser("~/vidigo"), "browser_profiles", "hepsiburada")
        os.makedirs(profile_dir, exist_ok=True)
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(profile_dir, headless=False)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_function(
                    self._CONTENT_READY_SCRIPT,
                    timeout=60_000,
                )
                # Rehber basligi gorundukten sonra sol menu verisi ayri bir istemci istegiyle gelir.
                # Menu dolmadan devam etmek, taramanin bos bitip pencerenin erken kapanmasina yol acar.
                await page.wait_for_function(
                    """() => document.querySelectorAll('main aside button').length >= 10""",
                    timeout=60_000,
                )
                await self._expand_all_menu_groups(page)
                pages = await self._collect_visible_guides(
                    page, include_children, progress_callback=progress_callback
                )
                return pages
            finally:
                await context.close()

    async def _expand_all_menu_groups(self, page):
        """Tüm iç içe kategori/ürün dallarını menü sabitlenene kadar açar."""
        # Her açılış yeni düğümler ekleyebilir. Bu yüzden başlangıçtaki düğüm
        # sayısına ya da sabit derinliğe güvenmek yerine, her seferinde ilk
        # kapalı dalı açıp DOM'u yeniden okuruz.
        for _ in range(500):
            closed_group = await self._first_closed_menu_group(page)
            if closed_group is None:
                return
            await closed_group.click()
            await page.wait_for_timeout(100)
        raise RuntimeError("Sol menü 500 açılır dal sınırına ulaştı.")

    async def _first_closed_menu_group(self, page):
        buttons = page.locator("main aside button")
        for index in range(await buttons.count()):
            button = buttons.nth(index)
            class_name = await button.get_attribute("class") or ""
            if "justify-between" not in class_name:
                continue
            aria_expanded = await button.get_attribute("aria-expanded")
            text = (await button.inner_text()).strip()
            if aria_expanded == "false" or (aria_expanded is None and self._is_closed_group(text)):
                return button
        return None

    @staticmethod
    def _is_closed_group(text):
        return "▸" in text or "chevron_right" in text

    async def _collect_visible_guides(self, page, include_children, progress_callback=None):
        """Sol menudeki yaprak rehberleri URL ve article metniyle toplar."""
        if not include_children:
            _notify_progress(progress_callback, "crawl_plan_ready", total_pages=1, source=self.name)
            _notify_progress(progress_callback, "page_started", current_page=1, total_pages=1, url=page.url)
            content = await self._page_markdown(page)
            _notify_progress(progress_callback, "page_finished", current_page=1, total_pages=1, url=page.url, saved=bool(content))
            return [content]

        # Menü sayfa değişiminde yeniden render edildiği için locator index'i
        # her tur değişebilir. Önce yaprakları metin + aynı metnin sırası ile
        # sabit bir iş listesine dönüştürüyoruz.
        leaves = page.locator("main aside button.block.w-full")
        leaf_targets = []
        duplicate_counts = {}
        for index in range(await leaves.count()):
            text = (await leaves.nth(index).inner_text()).strip()
            if not text:
                continue
            occurrence = duplicate_counts.get(text, 0)
            duplicate_counts[text] = occurrence + 1
            leaf_targets.append((text, occurrence))

        total_pages = min(len(leaf_targets), self.max_pages)
        _notify_progress(progress_callback, "crawl_plan_ready", total_pages=total_pages, source=self.name)
        pages = []
        seen_urls = set()
        for index, (text, occurrence) in enumerate(leaf_targets[: self.max_pages], start=1):
            leaf = await self._find_leaf(page, text, occurrence)
            if leaf is None:
                # Bazı accordion'lar rehber değişince üst dalı tekrar kapatır.
                # Tekrar açıp yalnızca bu yaprağı atlamak yerine yeniden dene.
                await self._expand_all_menu_groups(page)
                leaf = await self._find_leaf(page, text, occurrence)
            if leaf is None:
                _notify_progress(progress_callback, "page_finished", current_page=index, total_pages=total_pages, title=text, saved=False, skipped=True)
                continue

            _notify_progress(progress_callback, "page_started", current_page=index, total_pages=total_pages, title=text)
            previous_content = (await page.locator("main").inner_text()).strip()
            await leaf.click()
            await self._wait_for_new_article(page, previous_content)
            current_url = page.url
            if current_url in seen_urls:
                _notify_progress(progress_callback, "page_finished", current_page=index, total_pages=total_pages, url=current_url, title=text, saved=False, skipped=True)
                continue
            seen_urls.add(current_url)
            markdown = await self._page_markdown(page, title=text)
            if markdown:
                pages.append(markdown)
            _notify_progress(progress_callback, "page_finished", current_page=index, total_pages=total_pages, url=current_url, title=text, saved=bool(markdown))
        return pages

    @staticmethod
    async def _wait_for_new_article(page, previous_markdown):
        """SPA yönlendirmesinden sonra eski makalenin kaydedilmesini önler."""
        try:
            await page.wait_for_function(
                """previous => {
                    const main = document.querySelector('main');
                    const content = main && main.innerText.trim();
                    return content
                        && !content.includes('Guide yükleniyor')
                        && content !== previous;
                }""",
                arg=previous_markdown,
                timeout=5_000,
            )
        except Exception:
            # Aktif rehbere tekrar basıldığında içerik değişmez. Bu durumda
            # mevcut metin geçerlidir; URL tekilleştirme onu ikinci kez eklemez.
            await page.wait_for_timeout(150)

    @staticmethod
    async def _find_leaf(page, text, occurrence):
        leaves = page.locator("main aside button.block.w-full")
        matches = []
        for index in range(await leaves.count()):
            leaf = leaves.nth(index)
            if (await leaf.inner_text()).strip() == text:
                matches.append(leaf)
        return matches[occurrence] if occurrence < len(matches) else None

    @staticmethod
    async def _page_markdown(page, title=None):
        # Portal iki farklı içerik yüzü sunuyor: normal rehberler <article>
        # içindeyken, Postman benzeri API reference ekranı birden fazla div
        # ve kod örneği panelinden oluşuyor. Sol navigation'ı kaldırıp main'in
        # kalanını almak her iki görünümde de endpoint, parametre ve kodları
        # korur.
        main = page.locator("main")
        content = (await main.evaluate(
            """node => {
                const content = node.cloneNode(true);
                content.querySelectorAll('aside, nav, [role="navigation"], header, footer').forEach(
                    element => element.remove()
                );
                return content.innerText.trim();
            }"""
        )).strip()
        if not title:
            title = (await main.locator("h1").first.inner_text()).strip()
        return HepsiburadaPortalAdapter._format_page_markdown(content, title)

    @staticmethod
    def _format_page_markdown(content, title):
        """API reference panellerini okunabilir bölüm başlıklarıyla saklar."""
        content = re.sub(
            r"(?im)^\s*KOD\s+ÖRNEKLER[İI]\s*$",
            "## Kod Örnekleri",
            content or "",
        )
        title = (title or "").strip()
        if not title:
            return content.strip()

        # Başlık breadcrumb sonrasında içerikte yeniden görünebilir; menüdeki
        # başlık dosyada tek ve tutarlı bir H1 olarak kalsın.
        content = re.sub(rf"(?im)^\s*{re.escape(title)}\s*$", "", content, count=1).strip()
        return f"# {title}\n\n{content}".strip()


SITE_CRAWL_ADAPTERS = [
    TrendyolDocumentationAdapter(),
    IdeasoftStoplightAdapter(),
    MetaInstagramPlatformAdapter(),
    HepsiburadaPortalAdapter(),
]


def resolve_site_adapter(url):
    return next((adapter for adapter in SITE_CRAWL_ADAPTERS if adapter.matches(url)), None)


def _fetch_native_markdown(url):
    markdown_url = quote(f"{url.rstrip('/')}.md", safe=":/?&=%")
    request = Request(markdown_url, headers={"User-Agent": "Vidigo Markdown Downloader/1.0"})
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


def _notify_progress(progress_callback, event, **fields):
    if progress_callback is None:
        return
    try:
        progress_callback(event, **fields)
    except Exception:
        pass


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
