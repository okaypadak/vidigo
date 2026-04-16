import os
import shutil
import uuid
import logging
from flask import Flask, render_template, request, jsonify
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    CouldNotRetrieveTranscript,
)
from transcribers.whisper_transcriber import transcribe_whisper
from utils.file_utils import save_transcript_to_file
from utils.video_downloader import download_audio_generic
from utils.youtube_utils import extract_youtube_video_id

app = Flask(__name__)

UPLOAD_DIR = os.path.expanduser("~/")
AUDIO_DIR = os.path.join(UPLOAD_DIR, "audiofiles")
LOG_DIR = os.path.join(UPLOAD_DIR, "vidigo_logs")
LOG_PATH = os.path.join(LOG_DIR, "app.log")

os.makedirs(AUDIO_DIR, exist_ok=True)
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


def _download_mp3(url):
    downloaded_path = download_audio_generic(url)
    dest_path = os.path.join(AUDIO_DIR, os.path.basename(downloaded_path))
    shutil.move(downloaded_path, dest_path)
    return dest_path


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
        gpu_available = False
    return jsonify({"gpu": gpu_available})


@app.route("/instagram_transcribe", methods=["POST"])
def instagram_transcribe():
    data = request.get_json()
    url = data.get("url", "").strip()
    timestamps = data.get("timestamps", True)

    if not url or "instagram.com" not in url:
        return jsonify({"error": "Geçerli bir Instagram URL girin."}), 400

    try:
        logger.info("Instagram download started: %s", url)
        dest_path = _download_mp3(url)
        logger.info("Instagram audio saved: %s", dest_path)
    except Exception as e:
        logger.exception("Instagram download failed: %s", url)
        return jsonify({"error": f"İndirme hatası: {str(e)}"}), 500

    try:
        logger.info("Whisper transcription started: %s", dest_path)
        result = transcribe_whisper(dest_path, with_timestamps=timestamps)
        save_transcript_to_file(str(uuid.uuid4())[:8], {"engine": "whisper", "transcript": result})
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        logger.info("Whisper transcription done: %s", dest_path)
        return jsonify({"status": "success", "engine": "whisper", "text": text})
    except Exception as e:
        logger.exception("Whisper transcription failed: %s", dest_path)
        return jsonify({"error": f"Transkript hatası: {str(e)}"}), 500


@app.route("/youtube_transcribe", methods=["POST"])
def youtube_transcribe():
    data = request.get_json()
    url = data.get("url", "").strip()
    timestamps = data.get("timestamps", True)

    video_id = extract_youtube_video_id(url)
    if not video_id:
        return jsonify({"error": "Geçerli bir YouTube URL girin."}), 400

    # 1. İndir
    try:
        logger.info("YouTube download started: %s", url)
        dest_path = _download_mp3(url)
        logger.info("YouTube audio saved: %s", dest_path)
    except Exception as e:
        logger.exception("YouTube download failed: %s", url)
        return jsonify({"error": f"İndirme hatası: {str(e)}"}), 500

    # 2. YouTube API dene
    try:
        logger.info("YouTube transcript API requested for video_id=%s", video_id)
        api = YouTubeTranscriptApi()
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
        else:
            fetched = api.fetch(video_id, languages=("tr", "en"))
            transcript = fetched.to_raw_data()
        text = _build_timestamped_transcript_text(transcript) if timestamps else "\n".join(
            (item.get("text") or "").strip() for item in transcript if (item.get("text") or "").strip()
        )
        save_transcript_to_file(video_id, {
            "engine": "youtube_transcript_api",
            "video_id": video_id,
            "text": text,
            "transcript": transcript,
        })
        logger.info("YouTube API transcript found for video_id=%s", video_id)
        return jsonify({"status": "success", "engine": "youtube_api", "text": text})
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable, CouldNotRetrieveTranscript):
        logger.info("YouTube API transcript not found, falling back to Whisper: %s", dest_path)
    except Exception as e:
        logger.exception("YouTube API error for video_id=%s", video_id)
        logger.info("Falling back to Whisper: %s", dest_path)

    # 3. Whisper fallback
    try:
        result = transcribe_whisper(dest_path, with_timestamps=timestamps)
        save_transcript_to_file(str(uuid.uuid4())[:8], {"engine": "whisper", "transcript": result})
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        logger.info("Whisper fallback done: %s", dest_path)
        return jsonify({"status": "success", "engine": "whisper", "text": text})
    except Exception as e:
        logger.exception("Whisper fallback failed: %s", dest_path)
        return jsonify({"error": f"Transkript hatası: {str(e)}"}), 500


if __name__ == "__main__":
    logger.info("Starting Flask development server")
    app.run(debug=True)
