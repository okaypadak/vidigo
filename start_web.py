import json
import os
import shutil
import uuid
from flask import Flask, render_template, request, jsonify
from transcribers.whisper_transcriber import transcribe_whisper
from utils.file_utils import save_transcript_to_file
from utils.udemy_scraper import scrape_udemy_course
from utils.udemy_record import asenkron, asenkron_filtered
from utils.video_downloader import download_audio_generic

app = Flask(__name__)

UPLOAD_DIR = os.path.expanduser("~/")
WAV_DIR = os.path.join(UPLOAD_DIR, "wavfiles")
JSON_PATH = os.path.join(UPLOAD_DIR, "udemy_course_list.json")

os.makedirs(WAV_DIR, exist_ok=True)

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
    return jsonify({"gpu": gpu_available})

@app.route("/udemy_scraper", methods=["POST"])
def udemy_scraper():
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL boş olamaz."}), 400

    try:
        scrape_udemy_course(url)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/udemy_record", methods=["POST"])
def udemy_record():
    data = request.get_json()
    selected_section = data.get("selected")

    if not os.path.exists(JSON_PATH):
        return jsonify({"error": "JSON dosyası bulunamadı. Önce kazıma yapın."}), 404

    try:
        if selected_section == "__ALL__":
            asenkron(JSON_PATH)
        else:
            asenkron_filtered(JSON_PATH, [selected_section])
        return jsonify({"status": "recording_started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/wav_files", methods=["GET"])
def list_wav_files():
    try:
        files = [f for f in os.listdir(WAV_DIR) if f.endswith(".wav")]
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/transcribe", methods=["POST"])
def transcribe():
    url = request.form.get("url")
    if not url or not url.endswith(".wav"):
        return jsonify({"error": "Geçerli bir WAV dosyası yolu sağlanmalıdır."}), 400

    audio_path = os.path.join(WAV_DIR, os.path.basename(url))
    if not os.path.exists(audio_path):
        return jsonify({"error": f"Dosya bulunamadı: {audio_path}"}), 404

    try:
        result = transcribe_whisper(audio_path)
        video_id = str(uuid.uuid4())[:8]
        save_transcript_to_file(video_id, {
            "engine": "whisper",
            "transcript": result
        })
        return jsonify({
            "engine": "whisper",
            "transcript": result
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/udemy_sections", methods=["GET"])
def get_udemy_sections():
    try:
        if not os.path.exists(JSON_PATH):
            return jsonify({"error": "Kazıma yapılmamış. JSON dosyası bulunamadı."}), 404

        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        sections = [item["section"] for item in data]
        return jsonify({"sections": sections})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/download_audio", methods=["POST"])
def download_audio():
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL boş olamaz."}), 400

    try:
        downloaded_path = download_audio_generic(url)
        dest_path = os.path.join(WAV_DIR, os.path.basename(downloaded_path))
        shutil.move(downloaded_path, dest_path)
        return jsonify({"status": "success", "filename": os.path.basename(dest_path)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
