"""Siteye özgü doküman erişim stratejileri.

Her adapter yalnızca bağlantı keşfi ve içeriğe erişim biçiminden sorumludur.
Markdown temizleme ve dosyaya yazma genel tarama akışında kalır.
"""

import asyncio
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

    async def collect_interactively(self, url, include_children):
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
    """Ideasoft'un tarayıcıda render edilen Stoplight dokümanını toplar."""

    name = "ideasoft_stoplight"
    requires_interactive_collection = True
    max_pages = 100

    def matches(self, url):
        parsed = urlparse(url)
        return parsed.hostname == "apidoc.ideasoft.dev" and _normalized_path(url).startswith("/docs/")

    def discover(self, url, html, include_children):
        if not include_children:
            return None

        urls = self._documentation_tree_urls(html, url)
        if len(urls) <= 1:
            return None
        return CrawlAccessPlan(name=self.name, urls=urls)

    async def collect_interactively(self, url, include_children):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Ideasoft adapter'i icin Playwright gerekli.") from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                main = page.locator("main")
                await main.wait_for(state="visible", timeout=30_000)
                await page.wait_for_function(
                    """() => {
                        const main = document.querySelector('main');
                        return main && main.innerText.trim().length > 500;
                    }""",
                    timeout=30_000,
                )
                content = (await main.inner_text()).strip()
                return [content] if content else []
            finally:
                await browser.close()

    @classmethod
    def _documentation_tree_urls(cls, html, current_url):
        """Stoplight'ın render edilmiş sol menüsünden aynı doküman ağacını seçer."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        current = urlparse(current_url)
        root_path = _normalized_path(current_url)
        soup = BeautifulSoup(html or "", "html.parser")
        urls = []
        seen = set()

        for anchor in soup.find_all("a", href=True):
            candidate = urljoin(current_url, anchor["href"]).split("#", 1)[0]
            parsed = urlparse(candidate)
            path = _normalized_path(candidate)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.netloc.lower() != current.netloc.lower()
                or (path != root_path and not path.startswith(f"{root_path}/"))
            ):
                continue
            key = candidate.rstrip("/")
            if key not in seen:
                seen.add(key)
                urls.append(candidate)
                if len(urls) >= cls.max_pages:
                    break
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

    async def collect_interactively(self, url, include_children):
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
                pages = await self._collect_visible_guides(page, include_children)
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

    async def _collect_visible_guides(self, page, include_children):
        """Sol menudeki yaprak rehberleri URL ve article metniyle toplar."""
        if not include_children:
            return [await self._page_markdown(page)]

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

        pages = []
        seen_urls = set()
        for text, occurrence in leaf_targets[: self.max_pages]:
            leaf = await self._find_leaf(page, text, occurrence)
            if leaf is None:
                # Bazı accordion'lar rehber değişince üst dalı tekrar kapatır.
                # Tekrar açıp yalnızca bu yaprağı atlamak yerine yeniden dene.
                await self._expand_all_menu_groups(page)
                leaf = await self._find_leaf(page, text, occurrence)
            if leaf is None:
                continue

            previous_content = (await page.locator("main").inner_text()).strip()
            await leaf.click()
            await self._wait_for_new_article(page, previous_content)
            current_url = page.url
            if current_url in seen_urls:
                continue
            seen_urls.add(current_url)
            markdown = await self._page_markdown(page, title=text)
            if markdown:
                pages.append(markdown)
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


async def fetch_access_plan(plan):
    if not plan.use_native_markdown:
        return []

    semaphore = asyncio.Semaphore(6)

    async def fetch(url):
        async with semaphore:
            return await asyncio.to_thread(_fetch_native_markdown, url)

    return [page for page in await asyncio.gather(*(fetch(url) for url in plan.urls)) if page]
