from flask import Flask, request, jsonify, render_template
import os
import json
import whisper
import wave
import subprocess
from pytube import YouTube
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from vosk import Model as VoskModel, KaldiRecognizer
from deepspeech import Model as DSModel

app = Flask(__name__)
os.makedirs("transcripts", exist_ok=True)

# Transkript dosya yolu
def get_transcript_filepath(video_id):
    return f"transcripts/{video_id}.json"

# Transkript dosyaya kaydet
def save_transcript_to_file(video_id, data):
    with open(get_transcript_filepath(video_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Daha önceki transkripti oku
def load_transcript_from_file(video_id):
    path = get_transcript_filepath(video_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

# YouTube'dan sesi indir
def download_audio(video_url, output_filename="audio.wav"):
    yt = YouTube(video_url)
    audio_stream = yt.streams.filter(only_audio=True).first()
    mp4_path = audio_stream.download(filename="temp_audio.mp4")
    subprocess.call([
        "ffmpeg", "-y", "-i", mp4_path,
        "-ar", "16000", "-ac", "1", "-f", "wav", output_filename
    ])
    os.remove(mp4_path)
    return output_filename

# YouTube transcript API ile alma
def get_transcript_api(video_id, lang="tr"):
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        if transcript_list.find_manually_created_transcript([lang]):
            return transcript_list.find_manually_created_transcript([lang]).fetch()
        elif transcript_list.find_generated_transcript([lang]):
            return transcript_list.find_generated_transcript([lang]).fetch()
        else:
            return None
    except (TranscriptsDisabled, NoTranscriptFound):
        return None

# Whisper ile çeviri
def transcribe_whisper(audio_path, lang="tr", model_size="small"):
    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path, language=lang)
    return {"text": result["text"]}

# Vosk ile çeviri
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

# DeepSpeech ile çeviri
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

# Ana sayfa - arayüz
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

# API endpoint
@app.route("/transcribe", methods=["GET"])
def transcribe():
    url = request.args.get("url")
    engine = request.args.get("engine", "whisper")
    lang = request.args.get("lang", "tr")

    if not url:
        return jsonify({"error": "URL parametresi eksik."}), 400

    try:
        video = YouTube(url)
        video_id = video.video_id

        # 1. Daha önce kaydedilmiş mi?
        cached = load_transcript_from_file(video_id)
        if cached:
            return jsonify({
                "engine": cached.get("engine", "cached"),
                "transcript": cached.get("transcript")
            })

        # 2. YouTube transcript varsa
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

        # 3. Yoksa sesi indir
        audio_file = download_audio(url)

        # 4. Engine'e göre işle
        if engine == "whisper":
            result = transcribe_whisper(audio_file, lang)
        elif engine == "vosk":
            result = transcribe_vosk(audio_file)
        elif engine == "deepspeech":
            result = transcribe_deepspeech(audio_file)
        else:
            return jsonify({"error": f"Bilinmeyen engine: {engine}"}), 400

        os.remove(audio_file)

        # 5. Dosyaya kaydet
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
