import asyncio
import json
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from .base import SiteCrawlAdapter, _normalized_path, _notify_progress

class IdeasoftStoplightAdapter(SiteCrawlAdapter):
    """IdeaSoft Stoplight menüsündeki her yaprak rehberi tarayıcıda toplar."""

    name = "ideasoft_stoplight"
    requires_interactive_collection = True
    stoplight_project_id = "cHJqOjIzODAzMw"
    page_batch_size = 1

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
            # Aynı partideki sekmeler çerezleri ve Chromium sürecini paylaşır.
            # browser.new_page() her çağrıda ayrı bir BrowserContext açtığı için
            # 10'lu partilerde gereksiz kaynak tüketimine yol açıyordu.
            if hasattr(browser, "new_context"):
                context = await browser.new_context(viewport={"width": 1440, "height": 1000})
                page = await context.new_page()
            else:  # Test çiftleri ve eski Playwright uyumluluğu.
                context = None
                page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            try:
                urls = [url]
                if include_children:
                    # Stoplight menüsü sanallaştırılmış olabildiği için yalnızca
                    # ekranda o anda bulunan bağlantıları okumak eksik sonuç verir.
                    # Render edilmiş ağacı açıyoruz; eksiksiz sayfa planını ise aynı
                    # ağacın Stoplight TOC verisinden alıyoruz.
                    # Yalnızca sol menüyü render etmek için açılış sayfasını
                    # yükle; bu aşamada açılış dokümanını kaydetme.
                    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    await page.locator("main").wait_for(state="visible", timeout=30_000)
                    initial_content = None
                    try:
                        table_of_contents = await asyncio.to_thread(self._fetch_table_of_contents)
                    except Exception as exc:
                        raise RuntimeError(
                            "Ideasoft tam sol menu agaci Stoplight'tan alinamadi; "
                            "eksik sayfa kaydetmemek icin tarama durduruldu."
                        ) from exc
                    ideashop_url, menu_entries = self._ideashop_menu_entries(table_of_contents, url)
                    if not menu_entries:
                        raise RuntimeError("Ideashop API alt menu basliklari bulunamadi.")
                    await self._open_ideashop_menu(page, ideashop_url)
                    _notify_progress(
                        progress_callback, "crawl_menu_headings",
                        headings=self._menu_headings(table_of_contents), source=self.name,
                    )
                    _notify_progress(
                        progress_callback, "crawl_menu_opened",
                        title="Ideashop API", source=self.name,
                    )
                    for index, entry in enumerate(menu_entries, start=1):
                        _notify_progress(
                            progress_callback, "crawl_menu_item", index=index,
                            total_items=len(menu_entries), title=entry["title"],
                            depth=entry["depth"], source=self.name,
                        )
                    method_entries = self._ideashop_http_method_entries(table_of_contents, url)
                    if not method_entries:
                        raise RuntimeError("Ideashop API HTTP metodlari bulunamadi.")
                    urls = [entry["url"] for entry in method_entries]
                else:
                    initial_content = None
                    method_entries = []

                pages = []
                total_pages = len(urls)
                _notify_progress(
                    progress_callback, "crawl_plan_ready", total_pages=total_pages, source=self.name
                )
                async def collect(index, guide_url):
                    _notify_progress(
                        progress_callback, "page_started", current_page=index,
                        total_pages=total_pages, url=guide_url,
                    )
                    try:
                        if index == 1 and initial_content is not None:
                            content = initial_content
                        else:
                            content = ""
                            last_error = None
                            # Stoplight bazen ilk istemci yüklemesini yarıda
                            # kesebiliyor. Aynı URL'yi yeni bir sekmede bir kez
                            # daha denemek, tekil hataların tüm belgeyi eksiltmesini
                            # önler.
                            for _ in range(2):
                                guide_page = (
                                    await context.new_page()
                                    if context is not None
                                    else await browser.new_page(viewport={"width": 1440, "height": 1000})
                                )
                                try:
                                    content = await self._collect_page(guide_page, guide_url)
                                    break
                                except Exception as exc:
                                    last_error = exc
                                finally:
                                    close = getattr(guide_page, "close", None)
                                    if close is not None:
                                        await close()
                            if not content and last_error is not None:
                                raise last_error
                    except Exception as exc:
                        return index, "", str(exc)
                    return index, content, ""

                # Her parti tamamlanmadan sonraki 10 sayfa açılmaz. Böylece
                # sunucuya sınırsız kayan istek yükü gönderilmez; sonuçların ve
                # ilerleme kayıtlarının sırası URL planıyla birebir aynı kalır.
                last_group_title = None
                for batch_start in range(0, total_pages, self.page_batch_size):
                    batch_urls = urls[batch_start:batch_start + self.page_batch_size]
                    batch = await asyncio.gather(*(
                        collect(index, guide_url)
                        for index, guide_url in enumerate(batch_urls, start=batch_start + 1)
                    ))
                    for index, content, error in batch:
                        guide_url = urls[index - 1]
                        _notify_progress(
                            progress_callback, "page_finished", current_page=index,
                            total_pages=total_pages, url=guide_url, saved=bool(content),
                            skipped=not bool(content), error=error or None,
                        )
                        if content:
                            if method_entries:
                                method_entry = method_entries[index - 1]
                                group_title = method_entry["group_title"]
                                if group_title != last_group_title:
                                    pages.append(f"# {group_title}")
                                    last_group_title = group_title
                                pages.append(f"## {method_entry['method_title']}")
                            pages.append(content)
                # Grup/metod başlıkları ile içerik aynı Markdown belgesinin
                # parçalarıdır; dış katmanın araya `---` koymaması için tek
                # sayfa olarak döndürülür.
                return ["\n\n".join(pages)] if pages else []
            finally:
                if context is not None:
                    await context.close()
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
    def _menu_headings(cls, table_of_contents):
        """Stoplight menüsünün tarama öncesi gösterilecek üst başlıkları."""
        headings = []
        for item in (table_of_contents or {}).get("items", []):
            title = str(item.get("title") or "").strip()
            if title:
                headings.append(title)
        return headings

    @classmethod
    def _ideashop_menu_entries(cls, table_of_contents, current_url):
        """Ideashop API açıldığında görünen ilk seviye menü adlarını döndürür."""
        parsed = urlparse(current_url)
        path_parts = [part for part in _normalized_path(current_url).split("/") if part]
        if len(path_parts) < 2:
            return "", []
        root = next(
            (item for item in (table_of_contents or {}).get("items", [])
             if str(item.get("title") or "").strip() == "Ideashop API"),
            None,
        )
        if root is None:
            return "", []
        slug = str(root.get("slug") or "").strip()
        ideashop_url = (
            f"{parsed.scheme}://{parsed.netloc}/docs/{path_parts[1]}/"
            f"{quote(slug, safe='-._~')}" if slug else current_url
        )
        return ideashop_url, [
            {"title": str(item.get("title") or "").strip(), "depth": 0}
            for item in root.get("items", [])
            if str(item.get("title") or "").strip()
        ]

    @classmethod
    def _ideashop_http_method_urls(cls, table_of_contents, current_url):
        """Ideashop API gruplarının altındaki HTTP operasyon URL'lerini döndürür."""
        return [entry["url"] for entry in cls._ideashop_http_method_entries(
            table_of_contents, current_url
        )]

    @classmethod
    def _ideashop_http_method_entries(cls, table_of_contents, current_url):
        """HTTP operasyonlarını üst menü başlıklarıyla birlikte döndürür."""
        parsed = urlparse(current_url)
        path_parts = [part for part in _normalized_path(current_url).split("/") if part]
        if len(path_parts) < 2:
            return []
        root = next(
            (item for item in (table_of_contents or {}).get("items", [])
             if str(item.get("title") or "").strip() == "Ideashop API"),
            None,
        )
        if root is None:
            return []
        docs_root = f"{parsed.scheme}://{parsed.netloc}/docs/{path_parts[1]}"
        entries = []
        for group in root.get("items") or []:
            group_title = str(group.get("title") or "").strip()
            if not group_title:
                continue
            stack = list(reversed(group.get("items") or []))
            while stack:
                item = stack.pop()
                stack.extend(reversed(item.get("items") or []))
                slug = str(item.get("slug") or "").strip()
                if item.get("type") == "http_operation" and slug:
                    entries.append({
                        "group_title": group_title,
                        "method_title": str(item.get("title") or slug).strip(),
                        "url": f"{docs_root}/{quote(slug, safe='-._~')}",
                    })
        return entries

    @staticmethod
    async def _open_ideashop_menu(page, ideashop_url):
        """Sol menüdeki Ideashop API düğümünü açar; alt sayfalara geçmez."""
        try:
            target = page.locator('[title="Ideashop API"]')
            if await target.count():
                await target.first.click()
                await page.wait_for_timeout(250)
                return
        except (AttributeError, AssertionError):
            pass
        await page.goto(ideashop_url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(250)

    @staticmethod
    def _menu_markdown(entries):
        lines = ["# IdeaSoft Sol Menü"]
        for entry in entries:
            lines.append(f"{'  ' * entry['depth']}- {entry['title']}")
        return "\n".join(lines)

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
            # Bir düğümün kendi slug'ı olsa bile alt düğümleri varsa bu bir
            # menü/kapsayıcı sayfadır. Tarama planı yalnızca yaprak rehberleri
            # içermelidir; aksi halde aynı bölümü gereksizce yeniden indirir.
            if slug and not children:
                urls.append(f"{docs_root}/{quote(str(slug), safe='-._~')}")
        return urls

    @classmethod
    def _fetch_table_of_contents(cls):
        endpoint = (
            f"https://stoplight.io/api/v1/projects/{cls.stoplight_project_id}"
            "/table-of-contents?branch=main"
        )
        request = Request(endpoint, headers={"User-Agent": "TextForge Markdown Downloader/1.0"})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    async def _collect_page(page, url):
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        # Stoplight analitik istekleri ağı sürekli meşgul tutuyor; networkidle
        # beklemek her sayfada 15 saniyelik timeout'a düşüyordu. Bunun yerine
        # doğrudan işlenecek ana içeriğin hazır olduğunu doğruluyoruz.
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
            current = (await IdeasoftStoplightAdapter._documentation_content(main)).strip()
            if current and current == previous:
                return current
            previous = current
            await page.wait_for_timeout(interval_ms)
            elapsed_ms += interval_ms
        return previous

    @staticmethod
    async def _documentation_content(main):
        """Stoplight Editor içindeki kullanıcının hedeflediği içerik gövdesini döndürür."""
        try:
            return await main.evaluate(r"""node => {
                const xpath = '//*[@id="mosaic-provider-react-aria-0-1"]'
                    + '/div/div/div[2]/main/div/div[2]/div/div/div[2]/div[1]/div';
                // Yalnızca kullanıcının doğruladığı içerik düğümü alınır;
                // başka panel veya yedek seçici kullanılmaz.
                const content = document.evaluate(
                    xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue?.innerText || '';
                // Response gövdesi yüzlerce alanlık tekrar eden şemalar
                // içerir. Yalnızca metodun açıklaması ve istek parametreleri
                // gerektiğinden Responses başlığından sonrasını alma.
                return content.split(/\n\s*Responses\s*\n/i, 1)[0].trim();
            }""")
        except AttributeError:
            # Hafif test çiftleri yalnızca inner_text uygular.
            return await main.inner_text()
