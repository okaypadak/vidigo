import start_web


def test_crawl_url_to_markdown_route_saves_result(monkeypatch, tmp_path):
    records = []
    markdown_path = tmp_path / "page.md"
    monkeypatch.setattr(start_web, "crawl_url_to_markdown", lambda url, progress_callback=None: "# Page")
    monkeypatch.setattr(start_web, "save_web_markdown", lambda url, markdown, output_dir: str(markdown_path))
    monkeypatch.setattr(start_web, "save_download_record", lambda *args, **kwargs: records.append((args, kwargs)))

    response = start_web.app.test_client().post("/crawl_url_to_markdown", json={"url": "https://example.com/page"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["engine"] == "crawl4ai"
    assert payload["markdown_path"] == str(markdown_path)
    assert payload["text"] == "# Page"
    assert records[0][1]["platform"] == "web"
    assert records[0][1]["url"] == "https://example.com/page"


def test_crawl_url_to_markdown_route_can_include_child_pages(monkeypatch, tmp_path):
    def crawl_tree(url, progress_callback=None):
        progress_callback("crawl_plan_ready", total_pages=3, source="test")
        progress_callback("page_finished", current_page=1, total_pages=3, saved=True)
        progress_callback("page_finished", current_page=2, total_pages=3, saved=False, skipped=True)
        progress_callback("page_finished", current_page=3, total_pages=3, saved=True)
        return "# Root\n\n# Child", 2

    monkeypatch.setattr(start_web, "crawl_url_tree_to_markdown", crawl_tree)
    monkeypatch.setattr(start_web, "save_web_markdown", lambda url, markdown, output_dir: str(tmp_path / "pages.md"))
    monkeypatch.setattr(start_web, "save_download_record", lambda *args, **kwargs: None)

    response = start_web.app.test_client().post("/crawl_url_to_markdown", json={"url": "https://example.com/docs", "include_children": True})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["page_count"] == 2
    assert payload["crawl_stats"] == {
        "total_pages": 3,
        "scanned_pages": 3,
        "saved_pages": 2,
        "skipped_pages": 1,
    }
