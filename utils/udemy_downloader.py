import os
import uuid
import yt_dlp


def download_udemy_video(url, cookies_path="/home/kypdk/udemy_cookie.txt"):
    download_id = str(uuid.uuid4())[:8]
    output_dir = f"downloads/udemy_{download_id}"
    os.makedirs(output_dir, exist_ok=True)

    ydl_opts = {
        'cookiefile': cookies_path,
        'outtmpl': f'{output_dir}/%(playlist)s/%(chapter_number)s - %(chapter)s/%(playlist_index)s. %(title)s.%(ext)s',
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'ffmpeg_location': 'ffmpeg',
        'noplaylist': False,
        'quiet': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return output_dir
    except Exception as e:
        return {"error": f"Udemy videosu indirilemedi: {str(e)}"}