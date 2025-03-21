import os
import uuid
import yt_dlp


def download_udemy_video(url, cookies_path="udemy-cookies.txt"):
    download_id = str(uuid.uuid4())[:8]
    output_dir = f"downloads/udemy_{download_id}"
    os.makedirs(output_dir, exist_ok=True)

    ydl_opts = {
        'cookiefile': cookies_path,
        'outtmpl': f'{output_dir}/%(playlist)s/%(chapter_number)s - %(chapter)s/%(playlist_index)s. %(title)s.%(ext)s',
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'ffmpeg_location': 'ffmpeg',  # gerekirse tam yol verilebilir
        'noplaylist': False,  # playlist desteği açık kalsın (Udemy bölümlerinde faydalı)
        'quiet': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return output_dir
    except Exception as e:
        return {"error": f"Udemy videosu indirilemedi: {str(e)}"}