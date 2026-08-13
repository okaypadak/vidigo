import pytest

from utils import web_markdown


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


def test_sidebar_group_urls_selects_only_active_documentation_group():
    html = '''
    <ul class="subpages"><li><a class="active" href="/docs/root">Root</a></li><li><a href="/docs/child">Child</a></li></ul>
    <ul class="subpages"><li><a href="/docs/other">Other</a></li></ul>
    '''

    assert web_markdown._sidebar_group_urls(html, "https://example.com/docs/root") == [
        "https://example.com/docs/root",
        "https://example.com/docs/child",
    ]


def test_fetch_native_markdown_removes_front_matter_and_index_notice(monkeypatch):
    class Response:
        headers = {"Content-Type": "text/markdown; charset=utf-8"}

        def read(self):
            return b"---\nupdatedAt: today\n---\nFetch the complete documentation index at: https://example.com/llms.txt\n# Baslik\n[Baglanti](https://example.com)"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(web_markdown, "urlopen", lambda request, timeout: Response())

    assert web_markdown._fetch_native_markdown("https://example.com/docs/page") == "# Baslik\nBaglanti"
