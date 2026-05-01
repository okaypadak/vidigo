import os
import textwrap
import pytest
from utils.video_downloader import _vtt_to_txt


@pytest.fixture
def tmp_vtt(tmp_path):
    content = textwrap.dedent("""\
        WEBVTT
        Kind: captions
        Language: tr

        00:00:00.000 --> 00:00:03.000
        Merhaba dünya

        00:00:03.000 --> 00:00:06.000
        Merhaba dünya

        00:00:06.000 --> 00:00:09.000
        Bu bir test cümlesidir.

    """)
    p = tmp_path / "test.tr.vtt"
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_vtt_to_txt_creates_txt(tmp_vtt):
    txt_path = _vtt_to_txt(tmp_vtt)
    assert txt_path.endswith(".txt")
    assert os.path.isfile(txt_path)


def test_vtt_to_txt_removes_vtt(tmp_vtt):
    _vtt_to_txt(tmp_vtt)
    assert not os.path.isfile(tmp_vtt)


def test_vtt_to_txt_strips_timestamps(tmp_vtt):
    txt_path = _vtt_to_txt(tmp_vtt)
    text = open(txt_path, encoding="utf-8").read()
    assert "-->" not in text
    assert "WEBVTT" not in text


def test_vtt_to_txt_deduplicates(tmp_vtt):
    txt_path = _vtt_to_txt(tmp_vtt)
    text = open(txt_path, encoding="utf-8").read()
    lines = [l for l in text.splitlines() if l.strip()]
    assert lines.count("Merhaba dünya") == 1


def test_vtt_to_txt_keeps_content(tmp_vtt):
    txt_path = _vtt_to_txt(tmp_vtt)
    text = open(txt_path, encoding="utf-8").read()
    assert "Merhaba dünya" in text
    assert "Bu bir test cümlesidir." in text
