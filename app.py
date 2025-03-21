import json
import os
import subprocess
import uuid
import wave
import whisper
import yt_dlp
from deepspeech import Model as DSModel
from flask import Flask, request, jsonify, render_template
from pytube import YouTube
from vosk import Model as VoskModel, KaldiRecognizer
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

app = Flask(__name__)
os.makedirs("transcripts", exist_ok=True)
os.makedirs("downloads", exist_ok=True)


# Dosya yolu yardımcıları
def get_transcript_filepath(video_id):
    return f"transcripts/{video_id}.json"


def save_transcript_to_file(video_id, data):
    with open(get_transcript_filepath(video_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_transcript_from_file(video_id):
    path = get_transcript_filepath(video_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


# YouTube ses indirme (pytube + ffmpeg)
def download_audio_youtube(url, save_path="downloads", output_filename="audio.wav"):
    os.makedirs(save_path, exist_ok=True)

    temp_filename = f"{uuid.uuid4().hex[:8]}.%(ext)s"
    full_path = os.path.join(save_path, temp_filename)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': full_path,
        'postprocessors': [
            {  # MP3/WAV dönüştürücü
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }
        ],
        'ffmpeg_location': 'ffmpeg',  # veya tam path: 'C:/ffmpeg/bin/ffmpeg.exe'
        'noplaylist': True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.download([url])

    # WAV uzantılı dosyayı bulup dön
    for file in os.listdir(save_path):
        if file.endswith(".wav"):
            return os.path.join(save_path, file)

    raise FileNotFoundError("Ses dosyası bulunamadı.")


# Udemy video indirme (yt-dlp + cookies)
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


# YouTube transcript varsa al
def get_transcript_api(video_id, lang="tr"):
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        if transcript_list.find_manually_created_transcript([lang]):
            return transcript_list.find_manually_created_transcript([lang]).fetch()
        elif transcript_list.find_generated_transcript([lang]):
            return transcript_list.find_generated_transcript([lang]).fetch()
    except (TranscriptsDisabled, NoTranscriptFound):
        return None


# Transkripsiyon motorları
def transcribe_whisper(audio_path, lang="tr", model_size="small"):
    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path, language=lang)
    return {"text": result["text"]}


def transcribe_vosk(audio_path):
    model_path = "models/vosk-tr"
    if not os.path.exists(model_path):
        return {"error": "Vosk Türkçe modeli bulunamadı."}
    model = VoskModel(model_path)
    wf = wave.open(audio_path, "rb")
    rec = KaldiRecognizer(model, wf.getframerate())
    results = []

    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            res = json.loads(rec.Result())
            results.append(res.get("text", ""))
    res = json.loads(rec.FinalResult())
    results.append(res.get("text", ""))
    return {"text": " ".join(results)}


def transcribe_deepspeech(audio_path):
    model_path = "models/deepspeech/deepspeech.tflite"
    scorer_path = "models/deepspeech/tr.scorer"
    if not os.path.exists(model_path) or not os.path.exists(scorer_path):
        return {"error": "DeepSpeech modeli veya scorer dosyası eksik."}
    model = DSModel(model_path)
    model.enableExternalScorer(scorer_path)
    with wave.open(audio_path, "rb") as wf:
        audio = wf.readframes(wf.getnframes())
        result = model.stt(audio)
    return {"text": result}


# Ana sayfa
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


# Transkript API
@app.route("/transcribe", methods=["GET"])
def transcribe():
    url = request.args.get("url")
    engine = request.args.get("engine", "auto")  # Varsayılan olarak otomatik
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

        # Daha önce kaydedildiyse yükle
        cached = load_transcript_from_file(video_id)
        if cached:
            return jsonify({
                "engine": cached.get("engine", "cached"),
                "transcript": cached.get("transcript")
            })

        # -------- AUTO MODE --------
        if engine == "auto":
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
        elif engine == "deepspeech":
            result = transcribe_deepspeech(audio_path)
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
