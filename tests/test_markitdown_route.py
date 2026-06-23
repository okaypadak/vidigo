import os

import start_web


def test_convert_file_to_markdown_route_converts_file_path(monkeypatch, tmp_path):
    source_path = tmp_path / "doc.txt"
    markdown_path = tmp_path / "doc.md"
    source_path.write_text("hello", encoding="utf-8")

    records = []
    monkeypatch.setattr(start_web, "convert_file_to_markdown", lambda path: "# Doc")
    monkeypatch.setattr(start_web, "save_markdown_output", lambda path, markdown: str(markdown_path))
    monkeypatch.setattr(start_web, "save_download_record", lambda *args, **kwargs: records.append((args, kwargs)))

    client = start_web.app.test_client()
    response = client.post("/convert_file_to_markdown", json={"file_path": str(source_path)})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "success"
    assert payload["engine"] == "markitdown"
    assert payload["file_path"] == os.path.abspath(source_path)
    assert payload["markdown_path"] == str(markdown_path)
    assert payload["text"] == "# Doc"
    assert records
    assert records[0][1]["engine"] == "markitdown"
    assert records[0][1]["markdown_path"] == str(markdown_path)
