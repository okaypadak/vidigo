import os

import pytest

from utils import markitdown_converter


def test_convert_file_to_markdown_rejects_audio_video(tmp_path):
    video_path = tmp_path / "video.mp4"
    video_path.write_text("fake video", encoding="utf-8")

    with pytest.raises(ValueError, match="Whisper"):
        markitdown_converter.convert_file_to_markdown(str(video_path))


def test_convert_file_to_markdown_uses_markitdown_for_documents(monkeypatch, tmp_path):
    document_path = tmp_path / "note.txt"
    document_path.write_text("hello", encoding="utf-8")

    class FakeResult:
        text_content = "# Note\n\nhello"

    class FakeMarkItDown:
        def convert(self, path):
            assert path == os.path.abspath(document_path)
            return FakeResult()

    monkeypatch.setattr(markitdown_converter, "_load_markitdown", lambda: FakeMarkItDown)

    assert markitdown_converter.convert_file_to_markdown(str(document_path)) == "# Note\n\nhello"


def test_save_markdown_output_writes_md_file(tmp_path):
    source_path = tmp_path / "Report.pdf"

    markdown_path = markitdown_converter.save_markdown_output(str(source_path), "# Report", output_dir=str(tmp_path))

    assert markdown_path.endswith("Report.md")
    assert os.path.exists(markdown_path)
    assert open(markdown_path, encoding="utf-8").read() == "# Report\n"
