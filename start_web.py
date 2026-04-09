import json
import os
import shutil
import subprocess
import uuid
import logging
from flask import Flask, render_template, request, jsonify, send_file, after_this_request
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    CouldNotRetrieveTranscript,
)
from werkzeug.utils import secure_filename
from transcribers.whisper_transcriber import transcribe_whisper
from utils.file_utils import save_transcript_to_file
from utils.udemy_scraper import scrape_udemy_course
from utils.udemy_record import asenkron, asenkron_filtered
from utils.ffmpeg_utils import get_ffmpeg_binary
from utils.video_downloader import download_audio_generic
from utils.youtube_utils import extract_youtube_video_id

app = Flask(__name__)

UPLOAD_DIR = os.path.expanduser("~/")
WAV_DIR = os.path.join(UPLOAD_DIR, "wavfiles")
JSON_PATH = os.path.join(UPLOAD_DIR, "udemy_course_list.json")
LOG_DIR = os.path.join(UPLOAD_DIR, "vidigo_logs")
LOG_PATH = os.path.join(LOG_DIR, "app.log")

os.makedirs(WAV_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler()
    ],
)
logger = logging.getLogger(__name__)


def _format_timestamp(seconds):
    total_ms = max(int(round(float(seconds) * 1000)), 0)
    hours, remainder = divmod(total_ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"
    return f"{minutes:02}:{secs:02}.{millis:03}"


def _build_timestamped_transcript_text(transcript):
    lines = []
    for item in transcript:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        start = item.get("start")
        duration = item.get("duration")
        if start is None:
            lines.append(text)
            continue
        if duration is None:
            lines.append(f"[{_format_timestamp(start)}] {text}")
            continue
        end = float(start) + float(duration)
        lines.append(f"[{_format_timestamp(start)} - {_format_timestamp(end)}] {text}")
    return "\n".join(lines).strip()

@app.route("/", methods=["GET"])
def index():
    logger.info("Index page requested")
    return render_template("index.html")

@app.route("/status", methods=["GET"])
def status():
    try:
        import torch
        gpu_available = torch.cuda.is_available()
    except ImportError:
        logger.info("Torch not installed; GPU status unavailable")
        gpu_available = False
    logger.info("Status endpoint checked; gpu_available=%s", gpu_available)
    return jsonify({"gpu": gpu_available})

@app.route("/udemy_scraper", methods=["POST"])
def udemy_scraper():
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        logger.error("Udemy scraper called without URL")
        return jsonify({"error": "URL boş olamaz."}), 400

    try:
        logger.info("Starting Udemy scrape for url=%s", url)
        scrape_udemy_course(url)
        logger.info("Udemy scrape finished successfully for url=%s", url)
        return jsonify({"status": "success"})
    except Exception as e:
        logger.exception("Udemy scrape failed for url=%s", url)
        return jsonify({"error": str(e)}), 500

@app.route("/udemy_record", methods=["POST"])
def udemy_record():
    data = request.get_json()
    selected_section = data.get("selected")

    if not os.path.exists(JSON_PATH):
        logger.error("Udemy record JSON not found at %s", JSON_PATH)
        return jsonify({"error": "JSON dosyası bulunamadı. Önce kazıma yapın."}), 404

    try:
        if selected_section == "__ALL__":
            logger.info("Starting Udemy recording for all sections")
            asenkron(JSON_PATH)
        else:
            logger.info("Starting Udemy recording for sections=%s", selected_section)
            asenkron_filtered(JSON_PATH, [selected_section])
        logger.info("Udemy recording started successfully")
        return jsonify({"status": "recording_started"})
    except Exception as e:
        logger.exception("Udemy recording failed for selection=%s", selected_section)
        return jsonify({"error": str(e)}), 500

@app.route("/wav_files", methods=["GET"])
def list_wav_files():
    try:
        logger.info("Listing WAV files in %s", WAV_DIR)
        files = [f for f in os.listdir(WAV_DIR) if f.endswith(".wav")]
        return jsonify({"files": files})
    except Exception as e:
        logger.exception("Failed to list WAV files")
        return jsonify({"error": str(e)}), 500

@app.route("/upload_convert", methods=["POST"])
def upload_convert():
    if "file" not in request.files:
        logger.error("upload_convert called without file part")
        return jsonify({"error": "Dosya yuklenmedi."}), 400

    upload = request.files["file"]
    if not upload or upload.filename == "":
        logger.error("upload_convert received empty filename")
        return jsonify({"error": "Dosya secilmedi."}), 400

    safe_name = secure_filename(upload.filename)
    if not safe_name:
        logger.error("upload_convert could not derive safe filename")
        return jsonify({"error": "Gecerli bir dosya adi bulunamadi."}), 400
    logger.info("Processing upload file=%s as safe_name=%s", upload.filename, safe_name)

    ext = os.path.splitext(safe_name)[1]
    temp_name = f"upload_{uuid.uuid4().hex}{ext}"
    temp_path = os.path.join(WAV_DIR, temp_name)
    upload.save(temp_path)
    logger.info("Uploaded file saved to temp path %s", temp_path)

    base_name = os.path.splitext(safe_name)[0] or "audio"
    output_name = f"{base_name}_{uuid.uuid4().hex[:8]}.wav"
    output_path = os.path.join(WAV_DIR, output_name)
    logger.info("Prepared conversion output path %s", output_path)

    ffmpeg_bin = get_ffmpeg_binary()
    cmd = [ffmpeg_bin, "-y", "-i", temp_path, "-ac", "1", "-ar", "16000", output_path]

    try:
        logger.info("Running ffmpeg conversion for %s -> %s", temp_path, output_path)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if os.path.exists(output_path):
                os.remove(output_path)
            error_msg = (result.stderr or "FFmpeg failed").strip()
            logger.error("FFmpeg failed with code %s: %s", result.returncode, error_msg)
            return jsonify({"error": error_msg}), 500
        logger.info("FFmpeg conversion completed successfully: %s", output_name)
        return jsonify({"status": "success", "filename": output_name})
    except FileNotFoundError:
        logger.exception("FFmpeg binary not found: %s", ffmpeg_bin)
        return jsonify({"error": "FFmpeg binary not found. Please install ffmpeg."}), 500
    finally:
        try:
            if os.path.exists(temp_path):
                logger.info("Cleaning up temp file %s", temp_path)
                os.remove(temp_path)
        except Exception:
            pass

@app.route("/transcribe", methods=["POST"])
def transcribe():
    url = request.form.get("url")
    if not url or not url.endswith(".wav"):
        logger.error("Transcribe called with invalid url=%s", url)
        return jsonify({"error": "Geçerli bir WAV dosyası yolu sağlanmalıdır."}), 400

    audio_path = os.path.join(WAV_DIR, os.path.basename(url))
    if not os.path.exists(audio_path):
        logger.error("Transcribe file not found at %s", audio_path)
        return jsonify({"error": f"Dosya bulunamadı: {audio_path}"}), 404

    try:
        logger.info("Starting transcription for %s", audio_path)
        result = transcribe_whisper(audio_path, with_timestamps=True)
        video_id = str(uuid.uuid4())[:8]
        save_transcript_to_file(video_id, {
            "engine": "whisper",
            "transcript": result
        })
        logger.info("Transcription completed for %s with id=%s", audio_path, video_id)
        return jsonify({
            "engine": "whisper",
            "transcript": result
        })
    except Exception as e:
        logger.exception("Transcription failed for %s", audio_path)
        return jsonify({"error": str(e)}), 500

@app.route("/udemy_sections", methods=["GET"])
def get_udemy_sections():
    try:
        if not os.path.exists(JSON_PATH):
            logger.error("Udemy sections requested but JSON missing at %s", JSON_PATH)
            return jsonify({"error": "Kazıma yapılmamış. JSON dosyası bulunamadı."}), 404

        logger.info("Reading Udemy sections from %s", JSON_PATH)
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        sections = [item["section"] for item in data]
        logger.info("Udemy sections loaded; count=%s", len(sections))
        return jsonify({"sections": sections})
    except Exception as e:
        logger.exception("Failed to load Udemy sections from %s", JSON_PATH)
        return jsonify({"error": str(e)}), 500

@app.route("/download_audio", methods=["POST"])
def download_audio():
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        logger.error("download_audio called without URL")
        return jsonify({"error": "URL boş olamaz."}), 400

    try:
        logger.info("Starting audio download from %s", url)
        downloaded_path = download_audio_generic(url)
        dest_path = os.path.join(WAV_DIR, os.path.basename(downloaded_path))
        shutil.move(downloaded_path, dest_path)
        logger.info("Audio downloaded and stored at %s", dest_path)
        return jsonify({"status": "success", "filename": os.path.basename(dest_path)})
    except Exception as e:
        logger.exception("Audio download failed for url=%s", url)
        return jsonify({"error": str(e)}), 500

@app.route("/download_mp3", methods=["POST"])
def download_mp3():
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        logger.error("download_mp3 called without URL")
        return jsonify({"error": "URL boş olamaz."}), 400

    try:
        logger.info("Starting MP3 download from %s", url)
        downloaded_path = download_audio_generic(url, codec="mp3")
        filename = os.path.basename(downloaded_path)

        @after_this_request
        def cleanup(response):
            try:
                if os.path.exists(downloaded_path):
                    os.remove(downloaded_path)
            except Exception:
                logger.exception("Failed to clean up MP3 file %s", downloaded_path)
            return response

        logger.info("MP3 ready for download: %s", downloaded_path)
        return send_file(
            downloaded_path,
            as_attachment=True,
            download_name=filename,
            mimetype="audio/mpeg",
        )
    except Exception as e:
        logger.exception("MP3 download failed for url=%s", url)
        return jsonify({"error": str(e)}), 500

@app.route("/youtube_transcript", methods=["POST"])
def youtube_transcript():
    data = request.get_json()
    url = data.get("url", "").strip()

    video_id = extract_youtube_video_id(url)
    if not video_id:
        logger.error("YouTube transcript requested with invalid URL=%s", url)
        return jsonify({"error": "Geçerli bir YouTube URL girin."}), 400

    try:
        logger.info("Requesting YouTube transcript for video_id=%s", video_id)
        api = YouTubeTranscriptApi()
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
        else:
            fetched = api.fetch(video_id, languages=("tr", "en"))
            transcript = fetched.to_raw_data()
        plain_text = "\n".join([item.get("text", "") for item in transcript]).strip()
        text = _build_timestamped_transcript_text(transcript)
        save_transcript_to_file(video_id, {
            "engine": "youtube_transcript_api",
            "video_id": video_id,
            "transcript": transcript,
            "text": text,
            "plain_text": plain_text
        })
        logger.info("YouTube transcript retrieved successfully for video_id=%s", video_id)
        return jsonify({
            "status": "found",
            "video_id": video_id,
            "text": text,
            "plain_text": plain_text,
            "transcript": transcript
        })
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable, CouldNotRetrieveTranscript) as e:
        logger.warning("No transcript for video_id=%s: %s", video_id, e)
        return jsonify({"status": "missing", "error": str(e)}), 404
    except Exception as e:
        logger.exception("YouTube transcript retrieval failed for video_id=%s", video_id)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    logger.info("Starting Flask development server")
    app.run(debug=True)
