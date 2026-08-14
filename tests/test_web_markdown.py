import asyncio

import pytest

from utils import web_crawl_adapters, web_markdown


def test_validate_web_url_rejects_localhost():
    with pytest.raises(ValueError, match="Yerel"):
        web_markdown.validate_web_url("http://localhost:5000")


def test_crawl_url_to_markdown_uses_crawler(monkeypatch):
    async def fake_crawl(url):
        assert url == "https://example.com"
        return "# Baslik", 1

    monkeypatch.setattr(web_markdown, "validate_web_url", lambda url: url)
    monkeypatch.setattr(web_markdown, "_crawl", fake_crawl)

    assert web_markdown.crawl_url_to_markdown("https://example.com") == "# Baslik"


def test_crawl_url_tree_to_markdown_includes_children(monkeypatch):
    async def fake_crawl(url, include_children=False):
        assert include_children is True
        return "# Root\n\n---\n\n# Child", 2

    monkeypatch.setattr(web_markdown, "validate_web_url", lambda url: url)
    monkeypatch.setattr(web_markdown, "_crawl", fake_crawl)

    assert web_markdown.crawl_url_tree_to_markdown("https://example.com") == ("# Root\n\n---\n\n# Child", 2)


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


def test_ideasoft_adapter_selects_only_requested_documentation_tree():
    html = '''
    <a href="/docs/admin-api">Admin API</a>
    <a href="/docs/admin-api/products">Products</a>
    <a href="/docs/admin-api/orders#list">Orders</a>
    <a href="/docs/storefront-api">Storefront API</a>
    <a href="https://example.com/docs/admin-api/ignored">External</a>
    '''

    assert web_crawl_adapters.IdeasoftStoplightAdapter._documentation_tree_urls(
        html, "https://apidoc.ideasoft.dev/docs/admin-api"
    ) == [
        "https://apidoc.ideasoft.dev/docs/admin-api",
        "https://apidoc.ideasoft.dev/docs/admin-api/products",
        "https://apidoc.ideasoft.dev/docs/admin-api/orders",
    ]


def test_ideasoft_adapter_collects_rendered_main_content(monkeypatch):
    class Main:
        async def wait_for(self, **kwargs):
            return None

        async def inner_text(self):
            return "IdeaSoft API dokumani"

    class Page:
        def locator(self, selector):
            assert selector == "main"
            return Main()

        async def goto(self, url, **kwargs):
            assert url == "https://apidoc.ideasoft.dev/docs/admin-api"

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
    assert asyncio.run(adapter.collect_interactively(
        "https://apidoc.ideasoft.dev/docs/admin-api", include_children=True
    )) == ["IdeaSoft API dokumani"]


def test_hepsiburada_adapter_identifies_closed_menu_group():
    assert web_crawl_adapters.HepsiburadaPortalAdapter._is_closed_group("Urun Yonetimi chevron_right")
    assert web_crawl_adapters.HepsiburadaPortalAdapter._is_closed_group("Genel Bakis ▸")
    assert not web_crawl_adapters.HepsiburadaPortalAdapter._is_closed_group("Sikca Sorulan Sorular")


def test_hepsiburada_api_reference_uses_menu_title_and_code_example_heading():
    content = "API REFERENCE\nKategori Bilgilerini Alma\nKOD ÖRNEKLERİ\ncurl --request GET"

    assert web_crawl_adapters.HepsiburadaPortalAdapter._format_page_markdown(
        content, "Kategori Bilgilerini Alma"
    ) == "# Kategori Bilgilerini Alma\n\nAPI REFERENCE\n\n## Kod Örnekleri\ncurl --request GET"
