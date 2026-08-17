import os
import re
from urllib.parse import urlparse

from .base import SiteCrawlAdapter, _notify_progress

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

        profile_dir = os.path.join(os.path.expanduser("~/textforge"), "browser_profiles", "hepsiburada")
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
