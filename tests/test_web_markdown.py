import asyncio

import pytest

from utils import web_crawl_adapters, web_markdown


def test_validate_web_url_rejects_localhost():
    with pytest.raises(ValueError, match="Yerel"):
        web_markdown.validate_web_url("http://localhost:5000")


def test_crawl_url_to_markdown_uses_crawler(monkeypatch):
    async def fake_crawl(url, progress_callback=None):
        assert url == "https://example.com"
        return "# Baslik", 1

    monkeypatch.setattr(web_markdown, "validate_web_url", lambda url: url)
    monkeypatch.setattr(web_markdown, "_crawl", fake_crawl)

    assert web_markdown.crawl_url_to_markdown("https://example.com") == "# Baslik"


def test_crawl_url_tree_to_markdown_includes_children(monkeypatch):
    async def fake_crawl(url, include_children=False, progress_callback=None):
        assert include_children is True
        return "# Root\n\n---\n\n# Child", 2

    monkeypatch.setattr(web_markdown, "validate_web_url", lambda url: url)
    monkeypatch.setattr(web_markdown, "_crawl", fake_crawl)

    assert web_markdown.crawl_url_tree_to_markdown("https://example.com") == ("# Root\n\n---\n\n# Child", 2)


def test_crawl_reports_discovered_page_progress(monkeypatch):
    class Result:
        success = True
        markdown = "# Sayfa"

    class Crawler:
        def __init__(self, **kwargs):
            pass

        async def arun(self, **kwargs):
            return Result()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class BrowserConfig:
        def __init__(self, **kwargs):
            pass

    adapter = type("Adapter", (), {
        "requires_interactive_collection": False,
        "discover": lambda self, *_: web_crawl_adapters.CrawlAccessPlan(
            name="test", urls=["https://example.com/one", "https://example.com/two"]
        ),
    })()
    events = []
    monkeypatch.setattr(web_markdown, "_load_crawler", lambda: (Crawler, BrowserConfig, None, object, None, None, None, None, None, None))
    monkeypatch.setattr(web_markdown, "resolve_site_adapter", lambda url: adapter)
    monkeypatch.setattr(web_markdown, "_navigation_discovery_config", lambda: object())
    monkeypatch.setattr(web_markdown, "_crawler_run_config", lambda *args, **kwargs: object())
    async def no_native_pages(*args, **kwargs):
        return []

    monkeypatch.setattr(web_markdown, "fetch_access_plan", no_native_pages)

    markdown, count = asyncio.run(web_markdown._crawl(
        "https://example.com/root", include_children=True,
        progress_callback=lambda event, **fields: events.append((event, fields)),
    ))

    assert markdown == "# Sayfa\n\n---\n\n# Sayfa"
    assert count == 2
    assert ("crawl_plan_ready", {"total_pages": 2, "source": "test"}) in events
    assert [event for event, _ in events].count("page_started") == 2
    assert [event for event, _ in events].count("page_finished") == 2


def test_save_web_markdown_writes_file(tmp_path):
    path = web_markdown.save_web_markdown("https://example.com/docs", "# Docs", str(tmp_path))

    assert path.endswith("example.com_docs.md")
    assert open(path, encoding="utf-8").read() == "# Docs\n"


def test_simplify_markdown_removes_images_links_and_common_ui_text():
    markdown = "![Logo](https://example.com/logo.svg)\nCopy for LLM\n[Overview](https://example.com/docs)\n\n## See Also\n* [Other](https://example.com/other)\n\nDid you find this page helpful?"

    assert web_markdown.simplify_markdown(markdown) == "Overview"


def test_trendyol_adapter_selects_only_active_documentation_group():
    html = '''
    <ul class="subpages"><li><a class="active" href="/docs/root">Root</a></li><li><a href="/docs/child">Child</a></li></ul>
    <ul class="subpages"><li><a href="/docs/other">Other</a></li></ul>
    '''

    adapter = web_crawl_adapters.TrendyolDocumentationAdapter()

    assert adapter._active_sidebar_group_urls(html, "https://example.com/docs/root") == [
        "https://example.com/docs/root",
        "https://example.com/docs/child",
    ]


def test_native_markdown_access_removes_front_matter(monkeypatch):
    class Response:
        headers = {"Content-Type": "text/markdown; charset=utf-8"}

        def read(self):
            return b"---\nupdatedAt: today\n---\nFetch the complete documentation index at: https://example.com/llms.txt\n# Baslik\n[Baglanti](https://example.com)"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(web_crawl_adapters, "urlopen", lambda request, timeout: Response())

    assert web_crawl_adapters._fetch_native_markdown("https://example.com/docs/page") == "# Baslik\n[Baglanti](https://example.com)"


def test_resolve_site_adapter_uses_trendyol_adapter():
    adapter = web_crawl_adapters.resolve_site_adapter("https://developers.trendyol.com/docs/ornek")

    assert isinstance(adapter, web_crawl_adapters.TrendyolDocumentationAdapter)
    assert web_crawl_adapters.resolve_site_adapter("https://example.com/docs") is None


def test_resolve_site_adapter_uses_hepsiburada_adapter():
    adapter = web_crawl_adapters.resolve_site_adapter("https://developers.hepsiburada.com/tr/companies/hepsiburada")

    assert isinstance(adapter, web_crawl_adapters.HepsiburadaPortalAdapter)


def test_resolve_site_adapter_uses_ideasoft_adapter():
    adapter = web_crawl_adapters.resolve_site_adapter("https://apidoc.ideasoft.dev/docs/admin-api")

    assert isinstance(adapter, web_crawl_adapters.IdeasoftStoplightAdapter)


def test_resolve_site_adapter_uses_meta_instagram_adapter():
    adapter = web_crawl_adapters.resolve_site_adapter(
        "https://developers.facebook.com/documentation/instagram-platform"
    )

    assert isinstance(adapter, web_crawl_adapters.MetaInstagramPlatformAdapter)


def test_meta_instagram_adapter_selects_only_menu_urls_in_its_documentation_tree():
    adapter = web_crawl_adapters.MetaInstagramPlatformAdapter()

    assert adapter._menu_urls([
        "/documentation/instagram-platform",
        "/documentation/instagram-platform/overview",
        "/documentation/instagram-platform/instagram-api-with-instagram-login/get-started",
        "/documentation/instagram-platform.md",
        "/documentation/whatsapp",
        "https://example.com/documentation/instagram-platform/ignored",
    ], "https://developers.facebook.com/documentation/instagram-platform") == [
        "https://developers.facebook.com/documentation/instagram-platform",
        "https://developers.facebook.com/documentation/instagram-platform/overview",
        "https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started",
    ]


def test_meta_instagram_adapter_uses_curl_user_agent_for_markdown(monkeypatch):
    class Response:
        headers = {"Content-Type": "text/markdown; charset=utf-8"}

        def read(self):
            return b"# Meta rehberi"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    captured = {}

    def fake_urlopen(request, timeout):
        captured["user_agent"] = request.get_header("User-agent")
        return Response()

    monkeypatch.setattr(web_crawl_adapters, "urlopen", fake_urlopen)

    assert web_crawl_adapters.MetaInstagramPlatformAdapter._fetch_markdown(
        "https://developers.facebook.com/documentation/instagram-platform/overview"
    ) == "# Meta rehberi"
    assert captured["user_agent"] == "curl/8.0"


def test_ideasoft_adapter_flattens_every_leaf_in_stoplight_menu():
    table_of_contents = {"items": [
        {"id": "authentication", "slug": "authentication", "title": "Authentication"},
        {"title": "APIs", "items": [
            {"id": "products", "slug": "products-list", "title": "Products"},
            {"title": "Orders", "items": [
                {"id": "orders", "slug": "orders-list", "title": "Orders"},
            ]},
        ]},
    ]}

    assert web_crawl_adapters.IdeasoftStoplightAdapter._menu_leaf_urls(
        table_of_contents, "https://apidoc.ideasoft.dev/docs/admin-api"
    ) == [
        "https://apidoc.ideasoft.dev/docs/admin-api/authentication",
        "https://apidoc.ideasoft.dev/docs/admin-api/products-list",
        "https://apidoc.ideasoft.dev/docs/admin-api/orders-list",
    ]


def test_ideasoft_adapter_keeps_slugged_toc_entries_without_an_id():
    assert web_crawl_adapters.IdeasoftStoplightAdapter._menu_leaf_urls({"items": [
        {"slug": "unidentified-but-valid-page", "title": "Untitled"},
    ]}, "https://apidoc.ideasoft.dev/docs/admin-api") == [
        "https://apidoc.ideasoft.dev/docs/admin-api/unidentified-but-valid-page",
    ]


def test_ideasoft_adapter_merges_toc_and_rendered_menu_without_duplicates():
    assert web_crawl_adapters.IdeasoftStoplightAdapter._merge_menu_urls(
        "https://apidoc.ideasoft.dev/docs/admin-api",
        ["https://apidoc.ideasoft.dev/docs/admin-api/authentication"],
        ["https://apidoc.ideasoft.dev/docs/admin-api/authentication", "https://apidoc.ideasoft.dev/docs/admin-api/products"],
    ) == [
        "https://apidoc.ideasoft.dev/docs/admin-api",
        "https://apidoc.ideasoft.dev/docs/admin-api/authentication",
        "https://apidoc.ideasoft.dev/docs/admin-api/products",
    ]


def test_ideasoft_adapter_keeps_only_rendered_links_in_current_docs_tree():
    assert web_crawl_adapters.IdeasoftStoplightAdapter._menu_urls([
        "/docs/admin-api/authentication",
        "/docs/admin-api/abandoned-cart-list",
        "/docs/admin-api/authentication#overview",
        "/docs/other-api/ignored",
        "https://example.com/docs/admin-api/ignored",
    ], "https://apidoc.ideasoft.dev/docs/admin-api") == [
        "https://apidoc.ideasoft.dev/docs/admin-api/authentication",
        "https://apidoc.ideasoft.dev/docs/admin-api/abandoned-cart-list",
    ]


def test_ideasoft_adapter_collects_rendered_main_content(monkeypatch):
    class Main:
        async def wait_for(self, **kwargs):
            return None

        async def inner_text(self):
            return "IdeaSoft API dokumani"

    class MenuLocator:
        def __init__(self, selector):
            self.selector = selector

        async def count(self):
            return 0

        async def evaluate_all(self, script):
            assert self.selector == "a[href]"
            return ["/docs/admin-api/authentication"]

    class Page:
        visited_urls = []

        async def wait_for_load_state(self, **kwargs):
            return None

        async def wait_for_timeout(self, timeout):
            return None

        def locator(self, selector):
            if selector == "main":
                return Main()
            assert selector in {"button[aria-expanded='false']", "a[href]"}
            return MenuLocator(selector)

        async def goto(self, url, **kwargs):
            self.visited_urls.append(url)

        async def wait_for_function(self, script, **kwargs):
            assert "innerText" in script

    class Browser:
        async def new_page(self, **kwargs):
            return Page()

        async def close(self):
            return None

    class Playwright:
        class Chromium:
            async def launch(self, **kwargs):
                return Browser()

        chromium = Chromium()

    class PlaywrightContext:
        async def __aenter__(self):
            return Playwright()

        async def __aexit__(self, *args):
            return False

    import sys
    import types

    monkeypatch.setitem(sys.modules, "playwright.async_api", types.SimpleNamespace(
        async_playwright=lambda: PlaywrightContext()
    ))
    adapter = web_crawl_adapters.IdeasoftStoplightAdapter()
    monkeypatch.setattr(adapter, "_fetch_table_of_contents", lambda: {"items": [
        {"slug": "authentication", "title": "Authentication"},
    ]})
    assert asyncio.run(adapter.collect_interactively(
        "https://apidoc.ideasoft.dev/docs/admin-api", include_children=True
    )) == ["IdeaSoft API dokumani", "IdeaSoft API dokumani"]


def test_hepsiburada_adapter_identifies_closed_menu_group():
    assert web_crawl_adapters.HepsiburadaPortalAdapter._is_closed_group("Urun Yonetimi chevron_right")
    assert web_crawl_adapters.HepsiburadaPortalAdapter._is_closed_group("Genel Bakis ▸")
    assert not web_crawl_adapters.HepsiburadaPortalAdapter._is_closed_group("Sikca Sorulan Sorular")


def test_hepsiburada_api_reference_uses_menu_title_and_code_example_heading():
    content = "API REFERENCE\nKategori Bilgilerini Alma\nKOD ÖRNEKLERİ\ncurl --request GET"

    assert web_crawl_adapters.HepsiburadaPortalAdapter._format_page_markdown(
        content, "Kategori Bilgilerini Alma"
    ) == "# Kategori Bilgilerini Alma\n\nAPI REFERENCE\n\n## Kod Örnekleri\ncurl --request GET"
