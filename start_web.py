import os
import subprocess
import uuid

from flask import Flask, render_template, request, jsonify
from pytube import YouTube

from transcribers.vosk_transcriber import transcribe_vosk
from transcribers.whisper_transcriber import transcribe_whisper
from utils.file_utils import (
    get_transcript_filepath,
    save_transcript_to_file,
    load_transcript_from_file
)
from utils.transcript_api import get_transcript_api
from utils.udemy_downloader import download_udemy_video
from utils.youtube_downloader import download_audio_youtube

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/status", methods=["GET"])
def status():
    try:
        import torch
        gpu_available = torch.cuda.is_available()
    except ImportError:
        gpu_available = False

    return jsonify({
        "gpu": gpu_available
    })


@app.route("/transcribe", methods=["GET"])
def transcribe():
    url = request.args.get("url")
    engine = request.args.get("engine", "auto")
    lang = request.args.get("lang", "tr")

    if not url:
        return jsonify({"error": "URL parametresi eksik."}), 400

    try:
        is_youtube = "youtube.com" in url or "youtu.be" in url
        is_udemy = "udemy.com" in url

        if is_youtube:
            video_id = YouTube(url).video_id
        elif is_udemy:
            video_id = str(uuid.uuid4())[:8]
        else:
            return jsonify({"error": "Sadece YouTube ve Udemy destekleniyor."}), 400


        if engine == "transcript_api":
            if is_youtube:
                transcript = get_transcript_api(video_id, lang)
                if transcript:
                    save_transcript_to_file(video_id, {
                        "engine": "transcript_api",
                        "transcript": transcript
                    })
                    return jsonify({
                        "engine": "transcript_api",
                        "transcript": transcript
                    })
                else:
                    return jsonify({"error": "Otomatik YouTube transkripti bulunamadı."}), 404
            elif is_udemy:
                return jsonify(
                    {"error": "Udemy videolarında otomatik transkript desteklenmiyor. Lütfen bir engine seçin."}), 400

        # -------- ENGINE KULLANICI TARAFINDAN BELİRTİLDİ --------
        # Ses dosyasını hazırla
        if is_udemy:
            result = download_udemy_video(url)
            if isinstance(result, dict) and "error" in result:
                return jsonify(result), 500

            # İlk video dosyasını bul
            video_files = []
            for root, _, files in os.walk(result):
                for file in files:
                    if file.endswith((".mp4", ".mkv", ".webm")):
                        video_files.append(os.path.join(root, file))
            if not video_files:
                return jsonify({"error": "Udemy videosu indirildi ama video bulunamadı."}), 500

            video_path = video_files[0]
            audio_path = "audio.wav"
            subprocess.call([
                "ffmpeg", "-y", "-i", video_path,
                "-ar", "16000", "-ac", "1", "-f", "wav", audio_path
            ])
        else:
            audio_path = download_audio_youtube(url)

        # Engine'e göre transkripti üret
        if engine == "whisper":
            result = transcribe_whisper(audio_path, lang)
        elif engine == "vosk":
            result = transcribe_vosk(audio_path)
        else:
            return jsonify({"error": f"Bilinmeyen engine: {engine}"}), 400

        os.remove(audio_path)

        # Kaydet
        save_transcript_to_file(video_id, {
            "engine": engine,
            "transcript": result
        })

        return jsonify({
            "engine": engine,
            "transcript": result
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
