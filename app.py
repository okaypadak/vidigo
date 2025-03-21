from flask import Flask, request, jsonify, render_template
import os
import json
import subprocess
import wave
import uuid
import whisper
from pytube import YouTube
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from vosk import Model as VoskModel, KaldiRecognizer
from deepspeech import Model as DSModel

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
def download_audio_youtube(video_url, output_filename="audio.wav"):
    yt = YouTube(video_url)
    audio_stream = yt.streams.filter(only_audio=True).first()
    mp4_path = audio_stream.download(filename="temp_audio.mp4")
    subprocess.call([
        "ffmpeg", "-y", "-i", mp4_path,
        "-ar", "16000", "-ac", "1", "-f", "wav", output_filename
    ])
    os.remove(mp4_path)
    return output_filename


# Udemy video indirme (yt-dlp + cookies)
def download_udemy_video(url, cookies_path="udemy-cookies.txt"):
    download_id = str(uuid.uuid4())[:8]
    output_dir = f"downloads/udemy_{download_id}"
    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        "yt-dlp",
        "--cookies", cookies_path,
        "-o", f"{output_dir}/%(playlist)s/%(chapter_number)s - %(chapter)s/%(playlist_index)s. %(title)s.%(ext)s",
        url
    ]

    try:
        subprocess.run(cmd, check=True)
        return output_dir
    except subprocess.CalledProcessError as e:
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
    engine = request.args.get("engine", "whisper")
    lang = request.args.get("lang", "tr")

    if not url:
        return jsonify({"error": "URL parametresi eksik."}), 400

    try:
        video_id = str(uuid.uuid4())[:8] if "udemy.com" in url else YouTube(url).video_id

        # Daha önce kaydedildiyse yükle
        cached = load_transcript_from_file(video_id)
        if cached:
            return jsonify({
                "engine": cached.get("engine", "cached"),
                "transcript": cached.get("transcript")
            })

        # YouTube ise önce transcript API denenir
        if "youtube.com" in url:
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

        # Ses dosyasını indir
        if "udemy.com" in url:
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

        # Transkript motoruna göre işleme
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
