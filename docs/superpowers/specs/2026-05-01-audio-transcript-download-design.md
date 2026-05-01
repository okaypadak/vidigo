# Audio & Transcript Download — Design Spec

**Date:** 2026-05-01  
**Status:** Approved

## Overview

YouTube kanal, playlist ve tekil video indirmelerine iki ayrı mod eklenir:
- **MP3 İndir** (`mode="audio"`) — sadece ses dosyası
- **Transcript İndir** (`mode="transcript"`) — sadece düz metin transkript

İndirme kök dizini `~/audiofiles/` olur. Instagram akışı değişmez.

---

## Klasör Yapısı

```
C:\Users\<kullanıcı>\audiofiles\
  <kaynak_adı>\
    audio\
      Video Adı [id].mp3
    transcript\
      Video Adı [id].txt
```

Kaynak adı belirleme:
- Kanal → kanal adı (`@TechChannel` → `TechChannel`)
- Playlist → playlist başlığı
- Tek video → video başlığı

---

## `download_media` İmzası

```python
def download_media(url, cookie_path=None, mode="video", item_callback=None):
```

| mode | Davranış |
|------|----------|
| `"video"` | Mevcut video indirme, path güncellenir |
| `"audio"` | Ses indir, `audio/` alt klasörüne |
| `"transcript"` | Sadece transcript, `transcript/` alt klasörüne |

Mevcut `audio_only` parametresi kaldırılır. Instagram için:
```python
audio_only = (mode == "audio")
```

---

## Path Değişikliği

```python
# download_service.py
DOWNLOAD_ROOT = os.path.join(os.path.expanduser("~"), "audiofiles")
```

`_source_download_dir` fonksiyonu `mode` alır ve alt klasörü belirler:
- `mode="audio"` → `<kaynak_dir>/audio/`
- `mode="transcript"` → `<kaynak_dir>/transcript/`
- `mode="video"` → `<kaynak_dir>/` (alt klasör yok)

---

## Transcript Akışı

### yt-dlp Seçenekleri

```python
{
    "writeautomaticsub": True,
    "writesubtitles": True,
    "subtitleslangs": ["tr", "en"],  # önce tr, yoksa en
    "subtitlesformat": "vtt",
    "skip_download": True,           # ses/video indirme yapma
    "paths": {"subtitle": transcript_dir, "home": transcript_dir},
    "outtmpl": "%(title)s [%(id)s].%(ext)s",
}
```

### VTT → TXT Dönüşümü

Yeni yardımcı fonksiyon `_vtt_to_txt(vtt_path) -> txt_path`:
1. `.vtt` dosyasını oku
2. Regex ile `WEBVTT` header, timestamp satırları (`00:00:00.000 --> ...`), boş satırlar temizlenir
3. Tekrar eden satırlar kaldırılır (YouTube bazen aynı metni çakıştırır)
4. Temiz metin `.txt` olarak aynı dizine kaydedilir
5. `.vtt` dosyası silinir

Transkripti olmayan videolar atlanır (hata fırlatılmaz).

### Yeni Fonksiyon

```python
def download_youtube_transcript(url, save_path, cookie_path=None, item_callback=None):
    # playlist/kanal için tüm videolarda transcript çeker
    # tek video için tek transcript
```

---

## UI Değişiklikleri

`templates/index.html`:
- Mevcut "İndir" butonu kaldırılır
- **MP3 İndir** butonu → `mode=audio` ile POST
- **Transcript İndir** butonu → `mode=transcript` ile POST

`start_web.py`:
- `/download` endpoint'i `mode` parametresi alır (default `"video"`)
- `download_media(url, mode=mode, ...)` olarak çağrılır

---

## Etkilenmeyen Alanlar

- Instagram indirme akışı değişmez
- Mevcut `download_youtube_playlist`, `download_youtube_video` fonksiyonları değişmez
- Cookie ve manifest kayıt sistemi değişmez
