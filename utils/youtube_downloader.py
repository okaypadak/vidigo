import os, uuid, yt_dlp

def download_audio_youtube(url, save_path="downloads"):
    os.makedirs(save_path, exist_ok=True)

    temp_filename = f"{uuid.uuid4().hex[:8]}.%(ext)s"
    full_path = os.path.join(save_path, temp_filename)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': full_path,
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }
        ],
        'ffmpeg_location': 'ffmpeg',
        'noplaylist': True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    for file in os.listdir(save_path):
        if file.endswith(".wav"):
            return os.path.join(save_path, file)

    raise FileNotFoundError("Ses dosyası bulunamadı.")
