# yt-dlp Transcript Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** YouTube videoları için "Sadece Transkript" modunda ses indirmeden yt-dlp'nin otomatik altyazı özelliğini kullanarak `.txt` dosyası oluşturmak.

**Architecture:** `video_downloader.py`'ye yt-dlp subtitle indirme + VTT→TXT dönüşüm fonksiyonları eklenir. `start_web.py`'deki `_process_audio_item` fonksiyonu `mode="transcript_only"` + `platform="youtube"` kombinasyonunda mevcut ses-indir-sonra-API-çağır akışı yerine yeni yt-dlp akışını kullanır. Diğer modlar ve Instagram akışı değişmez.

**Tech Stack:** yt-dlp (mevcut), Python re (stdlib), mevcut Flask/TinyDB yapısı

---

## Dosya Haritası

| Dosya | Değişim |
|-------|---------|
| `utils/video_downloader.py` | `_vtt_to_txt` + `download_youtube_transcript_ytdlp` eklenir |
| `start_web.py` | `_process_audio_item` içinde YouTube transcript_only dalı eklenir; `_ytdlp_transcript_path` yardımcısı eklenir |

---

## Task 1: `_vtt_to_txt` yardımcı fonksiyonu

**Files:**
- Modify: `utils/video_downloader.py` (dosyanın sonuna ekle)

- [ ] **Adım 1: Testi yaz**

`tests/test_vtt_to_txt.py` oluştur:

```python
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
```

- [ ] **Adım 2: Testi çalıştır, başarısız olduğunu doğrula**

```
cd c:/Users/PC/Documents/GitHub/vidigo
python -m pytest tests/test_vtt_to_txt.py -v
```

Beklenen çıktı: `ERROR` veya `ImportError: cannot import name '_vtt_to_txt'`

- [ ] **Adım 3: `_vtt_to_txt` fonksiyonunu yaz**

`utils/video_downloader.py` dosyasının sonuna ekle (import'lar bölümünde `import re` zaten var mı kontrol et, yoksa dosyanın başına ekle):

```python
def _vtt_to_txt(vtt_path):
    """VTT altyazı dosyasını düz metne çevirir, VTT dosyasını siler."""
    with open(vtt_path, encoding="utf-8") as f:
        raw = f.read()

    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*", line):
            continue
        if re.match(r"^\d+$", line):
            continue
        lines.append(line)

    # Ardışık tekrar eden satırları kaldır
    deduped = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)

    txt_path = re.sub(r"\.[a-z]{2,3}\.vtt$", ".txt", vtt_path)
    if txt_path == vtt_path:
        txt_path = os.path.splitext(vtt_path)[0] + ".txt"

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(deduped))

    os.remove(vtt_path)
    return txt_path
```

- [ ] **Adım 4: Testleri çalıştır, geçtiğini doğrula**

```
python -m pytest tests/test_vtt_to_txt.py -v
```

Beklenen: 5 test PASS

- [ ] **Adım 5: Commit**

```bash
git add utils/video_downloader.py tests/test_vtt_to_txt.py
git commit -m "feat: add _vtt_to_txt helper for subtitle conversion"
```

---

## Task 2: `download_youtube_transcript_ytdlp` fonksiyonu

**Files:**
- Modify: `utils/video_downloader.py` (Task 1'in hemen altına ekle)

- [ ] **Adım 1: Testi yaz**

`tests/test_ytdlp_transcript.py` oluştur:

```python
import os
import pytest
from unittest.mock import patch, MagicMock
from utils.video_downloader import download_youtube_transcript_ytdlp


def test_returns_list(tmp_path):
    fake_vtt = tmp_path / "Video Adi [abc123].tr.vtt"
    fake_vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nTest metni\n", encoding="utf-8")

    with patch("utils.video_downloader.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = lambda s: s
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "entries": [{"id": "abc123", "title": "Video Adi", "webpage_url": "https://youtube.com/watch?v=abc123"}]
        }
        mock_ydl_cls.return_value = mock_ydl

        with patch("utils.video_downloader._find_vtt_files", return_value=[str(fake_vtt)]):
            with patch("utils.video_downloader._vtt_to_txt", return_value=str(tmp_path / "Video Adi [abc123].txt")):
                result = download_youtube_transcript_ytdlp("https://youtube.com/@TestChannel", save_path=str(tmp_path))

    assert isinstance(result, list)


def test_empty_on_no_vtt(tmp_path):
    with patch("utils.video_downloader.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = lambda s: s
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": []}
        mock_ydl_cls.return_value = mock_ydl

        with patch("utils.video_downloader._find_vtt_files", return_value=[]):
            result = download_youtube_transcript_ytdlp("https://youtube.com/@TestChannel", save_path=str(tmp_path))

    assert result == []
```

- [ ] **Adım 2: Testi çalıştır, başarısız olduğunu doğrula**

```
python -m pytest tests/test_ytdlp_transcript.py -v
```

Beklenen: `ImportError: cannot import name 'download_youtube_transcript_ytdlp'`

- [ ] **Adım 3: Fonksiyonu yaz**

`utils/video_downloader.py` dosyasına `_vtt_to_txt`'in hemen altına ekle:

```python
def _find_vtt_files(directory):
    result = []
    for root, _, filenames in os.walk(directory):
        for fname in filenames:
            if fname.endswith(".vtt"):
                result.append(os.path.join(root, fname))
    return result


def download_youtube_transcript_ytdlp(url, save_path, cookie_path=None):
    """yt-dlp ile YouTube altyazısını indirir, VTT→TXT çevirir. Ses indirmez."""
    abs_save_path = os.path.abspath(save_path)
    os.makedirs(abs_save_path, exist_ok=True)
    ffmpeg_dir = get_ffmpeg_dir()

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": YtDlpMessageBridge("youtube.transcript"),
        "windowsfilenames": True,
        "cookiefile": cookie_path,
        "ffmpeg_location": str(ffmpeg_dir) if ffmpeg_dir else "ffmpeg",
        "skip_download": True,
        "writeautomaticsub": True,
        "writesubtitles": True,
        "subtitleslangs": ["tr", "en"],
        "subtitlesformat": "vtt",
        "paths": {"home": abs_save_path, "subtitle": abs_save_path},
        "outtmpl": "%(title)s [%(id)s].%(ext)s",
        "ignoreerrors": True,
        "extractor_args": {
            "youtube": {"player_client": ["android", "ios", "web"]}
        },
    }

    log_info(
        logger,
        "yt-dlp altyazi indirme basladi",
        stage="youtube.transcript",
        url=url,
        save_path=abs_save_path,
    )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)

    vtt_files = _find_vtt_files(abs_save_path)
    items = []
    for vtt_path in vtt_files:
        try:
            txt_path = _vtt_to_txt(vtt_path)
            items.append({"txt_path": txt_path, "vtt_source": vtt_path})
            log_info(logger, "VTT metin dosyasina donusturuldu", stage="youtube.transcript", txt_path=txt_path)
        except Exception:
            log_exception(logger, "VTT donusturme basarisiz", stage="youtube.transcript", vtt_path=vtt_path)

    log_info(
        logger,
        "yt-dlp altyazi indirme tamamlandi",
        stage="youtube.transcript",
        url=url,
        item_count=len(items),
    )
    return items
```

- [ ] **Adım 4: Testleri çalıştır, geçtiğini doğrula**

```
python -m pytest tests/test_ytdlp_transcript.py -v
```

Beklenen: 2 test PASS

- [ ] **Adım 5: Commit**

```bash
git add utils/video_downloader.py tests/test_ytdlp_transcript.py
git commit -m "feat: add download_youtube_transcript_ytdlp for subtitle-only download"
```

---

## Task 3: `start_web.py`'de transcript_only akışını yt-dlp ile güncelle

**Files:**
- Modify: `start_web.py` — `_process_audio_item` fonksiyonu (~satır 373)

Mevcut `_process_audio_item` şu an `mode="transcript_only"` durumunda:
1. `_download_mp3(url)` → MP3 indirir
2. `_youtube_api(video_id)` → transcript alır
3. MP3 siler

Yeni akış `mode="transcript_only"` + `platform="youtube"` için:
1. `download_youtube_transcript_ytdlp(url, transcript_dir)` → VTT indirir, TXT yapar
2. MP3 hiç indirilmez

- [ ] **Adım 1: Testi yaz**

`tests/test_process_audio_item_transcript.py` oluştur:

```python
import os
import pytest
from unittest.mock import patch, MagicMock


def test_transcript_only_youtube_skips_mp3(tmp_path):
    """mode=transcript_only + youtube → MP3 indirilmemeli"""
    fake_txt = str(tmp_path / "audiofiles" / "TestChannel" / "transcript" / "Video [id1].txt")
    os.makedirs(os.path.dirname(fake_txt), exist_ok=True)
    open(fake_txt, "w").write("Test metni")

    with patch("start_web.AUDIO_DIR", str(tmp_path / "audiofiles")):
        with patch("start_web.classify_download_url", return_value={"platform": "youtube", "source_type": "video", "url": "https://youtube.com/watch?v=id1"}):
            with patch("start_web.resolve_cookie_file", return_value=None):
                with patch("start_web.extract_youtube_video_id", return_value="id1"):
                    with patch("start_web.download_youtube_transcript_ytdlp", return_value=[{"txt_path": fake_txt}]) as mock_yt:
                        with patch("start_web._download_mp3") as mock_mp3:
                            with patch("start_web.upsert_manifest_item", return_value=("/fake/manifest.json", {})):
                                with patch("start_web.upsert_download_record"):
                                    from start_web import _process_audio_item
                                    item, _, _ = _process_audio_item(
                                        "https://youtube.com/watch?v=id1",
                                        mode="transcript_only",
                                    )
                                    mock_mp3.assert_not_called()
                                    mock_yt.assert_called_once()
```

- [ ] **Adım 2: Testi çalıştır, başarısız olduğunu doğrula**

```
python -m pytest tests/test_process_audio_item_transcript.py -v
```

Beklenen: FAIL (mock_mp3.assert_not_called() fails çünkü şu an mp3 indiriyor)

- [ ] **Adım 3: `start_web.py` import'una ekle**

`start_web.py` dosyasının `from utils.video_downloader import ...` satırına `download_youtube_transcript_ytdlp` ekle:

```python
from utils.video_downloader import (
    build_unique_filepath,
    download_audio_generic,
    download_youtube_transcript_ytdlp,  # YENİ
    extract_instagram_shortcode,
    list_youtube_video_urls,
    resolve_cookie_file,
)
```

- [ ] **Adım 4: `_ytdlp_transcript_dir` yardımcısını ekle**

`start_web.py`'de `_normalize_audio_path` fonksiyonunun hemen altına ekle (~satır 96):

```python
def _ytdlp_transcript_dir(source_name=None):
    safe_name = sanitize_filename(source_name) if source_name else "unknown"
    path = os.path.join(AUDIO_DIR, safe_name, "transcript")
    os.makedirs(path, exist_ok=True)
    return path
```

`sanitize_filename`'i import etmek için `start_web.py`'nin `from utils.video_downloader import` satırına `sanitize_filename` ekle (zaten var mı kontrol et).

- [ ] **Adım 5: `_process_audio_item` içine YouTube transcript dalını ekle**

`start_web.py` satır 373'teki `_process_audio_item` fonksiyonunda, `request = classify_download_url(url)` satırından sonra gelen bölümü bul. `dest_path = _download_mp3(...)` satırından **önce** şu dalı ekle:

```python
    # YouTube + transcript_only → ses indirmeden yt-dlp subtitle
    if mode == "transcript_only" and platform == "youtube":
        source_name_for_dir = hint_folder or extract_youtube_channel_name(url) or None
        transcript_dir = _ytdlp_transcript_dir(source_name_for_dir)
        txt_items = download_youtube_transcript_ytdlp(url, save_path=transcript_dir, cookie_path=resolved_cookie)

        # Her .txt için kayıt oluştur
        result_items = []
        manifest_path = None
        for txt_item in txt_items:
            txt_path = txt_item.get("txt_path")
            if not txt_path or not os.path.isfile(txt_path):
                continue
            video_name = os.path.splitext(os.path.basename(txt_path))[0]
            text = open(txt_path, encoding="utf-8").read()
            item_data = {
                "id": None,
                "video_id": None,
                "shortcode": None,
                "title": video_name,
                "platform": "youtube",
                "uploader": source_name_for_dir,
                "source_url": url,
                "webpage_url": url,
                "file_name": os.path.basename(txt_path),
                "file_path": txt_path,
                "downloaded_at": datetime.now().isoformat(),
                "engine": "ytdlp_subtitle",
                "transcript": text,
            }
            try:
                mp, _ = upsert_manifest_item(
                    "youtube",
                    source_name_for_dir or video_name,
                    item_source_type,
                    item_source_url,
                    item_data,
                    downloader="yt-dlp",
                    download_dir=transcript_dir,
                    engine="ytdlp_subtitle",
                )
                item_data["manifest_path"] = mp
                manifest_path = mp or manifest_path
            except Exception:
                log_exception(logger, "Transcript manifest yazılamadı", stage="transcript.manifest", txt_path=txt_path)
            try:
                upsert_download_record(
                    video_name=video_name,
                    transcript=text,
                    platform="youtube",
                    source_type=item_source_type,
                    source_name=source_name_for_dir or video_name,
                    source_url=item_source_url,
                    engine="ytdlp_subtitle",
                    url=url,
                    file_name=os.path.basename(txt_path),
                    file_path=txt_path,
                    uploader=source_name_for_dir,
                    downloader="yt-dlp",
                    manifest_path=manifest_path,
                )
            except Exception:
                log_exception(logger, "Transcript DB kaydı yazılamadı", stage="transcript.db", txt_path=txt_path)
            result_items.append(item_data)

        # Tek item döndür (caller tekil item bekliyor)
        if not result_items:
            raise FileNotFoundError("YouTube altyazısı bulunamadı. Video için altyazı mevcut olmayabilir.")
        first = result_items[0]
        return first, manifest_path, resolved_cookie
```

Bu return, mevcut `dest_path = _download_mp3(...)` satırından önce çalışır ve fonksiyondan erken çıkar.

- [ ] **Adım 6: Testleri çalıştır, geçtiğini doğrula**

```
python -m pytest tests/test_process_audio_item_transcript.py -v
```

Beklenen: PASS

- [ ] **Adım 7: Commit**

```bash
git add start_web.py tests/test_process_audio_item_transcript.py
git commit -m "feat: use yt-dlp subtitle for YouTube transcript_only mode"
```

---

## Task 4: Manuel test

- [ ] **Adım 1: Sunucuyu başlat**

```
python start_web.py
```

- [ ] **Adım 2: Tek video transcript testi**

Tarayıcıda `http://127.0.0.1:5000` aç, bir YouTube video URL'si gir, "Sadece Transkript" butonuna bas.

Beklenen:
- `~/audiofiles/<kanal_adı>/transcript/` klasörünün oluşması
- İçinde `.txt` dosyası (zaman damgasız Türkçe veya İngilizce metin)
- Log akışında `youtube.transcript` stage mesajları

- [ ] **Adım 3: Kanal URL testi**

Birkaç videolu küçük bir YouTube kanalı URL'si gir (`https://www.youtube.com/@...`), "Sadece Transkript" bas.

Beklenen:
- Her video için ayrı `.txt` dosyası
- MP3 dosyası oluşmaması

- [ ] **Adım 4: Altyazısız video testi**

Altyazısı olmayan bir video URL'si dene.

Beklenen: `"YouTube altyazısı bulunamadı"` hata mesajı, uygulama çökmemeli.

- [ ] **Adım 5: Son commit**

```bash
git add -A
git commit -m "test: manual validation of yt-dlp transcript feature"
```
