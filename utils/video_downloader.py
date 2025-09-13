import os
import yt_dlp

def sanitize_filename(name):
    return ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in name).replace(' ', '_')

def download_audio_generic(url, save_path="downloads"):
    os.makedirs(save_path, exist_ok=True)

    # URL'den önce info alalım
    with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        title = sanitize_filename(info.get("title", "video"))
        uploader = sanitize_filename(info.get("uploader", "channel"))

    # Hedef dosya adı
    filename = f"{uploader}-{title}.%(ext)s"
    full_path = os.path.join(save_path, filename)

    # Eğer X.com videosuysa cookie dosyasını kullan
    cookie_path = os.path.expanduser("~/cookie/x.com.txt") if "x.com" in url or "twitter.com" in url else None

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': full_path,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'cookiefile': cookie_path,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # .wav dosyasını bul
    for file in os.listdir(save_path):
        if file.endswith(".wav") and file.startswith(f"{uploader}-{title}"):
            return os.path.join(save_path, file)

    raise FileNotFoundError("Ses dosyası bulunamadı.")
