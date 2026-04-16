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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.expanduser("~/")
AUDIO_DIR = os.path.join(UPLOAD_DIR, "audiofiles")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
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


def _plain_transcript(transcript):
    return "\n".join(
        (item.get("text") or "").strip()
        for item in transcript if (item.get("text") or "").strip()
    )


def _download_mp3(url):
    downloaded_path = download_audio_generic(url, save_path=DOWNLOAD_DIR)
    dest_path = os.path.join(AUDIO_DIR, os.path.basename(downloaded_path))
    shutil.move(downloaded_path, dest_path)
    return dest_path


def _whisper(dest_path):
    result = transcribe_whisper(dest_path)
    return result if isinstance(result, str) else str(result)


def _youtube_api(video_id):
    api = YouTubeTranscriptApi()
    if hasattr(YouTubeTranscriptApi, "get_transcript"):
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
    else:
        fetched = api.fetch(video_id, languages=("tr", "en"))
        transcript = fetched.to_raw_data()
    return _plain_transcript(transcript), transcript


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


@app.route("/instagram_transcribe", methods=["POST"])
def instagram_transcribe():
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url or "instagram.com" not in url:
        return jsonify({"error": "Geçerli bir Instagram URL girin."}), 400

    try:
        logger.info("Instagram download started: %s", url)
        dest_path = _download_mp3(url)
    except Exception as e:
        logger.exception("Instagram download failed: %s", url)
        return jsonify({"error": f"İndirme hatası: {str(e)}"}), 500

    try:
        text = _whisper(dest_path)
        save_transcript_to_file(str(uuid.uuid4())[:8], {"engine": "whisper", "transcript": text})
        logger.info("Whisper done: %s", dest_path)
        return jsonify({"status": "success", "engine": "whisper", "text": text})
    except Exception as e:
        logger.exception("Whisper failed: %s", dest_path)
        return jsonify({"error": f"Transkript hatası: {str(e)}"}), 500


@app.route("/youtube_transcribe", methods=["POST"])
def youtube_transcribe():
    data = request.get_json()
    url = data.get("url", "").strip()

    video_id = extract_youtube_video_id(url)
    if not video_id:
        return jsonify({"error": "Geçerli bir YouTube URL girin."}), 400

    try:
        logger.info("YouTube download started: %s", url)
        dest_path = _download_mp3(url)
    except Exception as e:
        logger.exception("YouTube download failed: %s", url)
        return jsonify({"error": f"İndirme hatası: {str(e)}"}), 500

    try:
        text, transcript = _youtube_api(video_id)
        save_transcript_to_file(video_id, {"engine": "youtube_api", "video_id": video_id, "text": text, "transcript": transcript})
        logger.info("YouTube API transcript found: %s", video_id)
        return jsonify({"status": "success", "engine": "youtube_api", "text": text})
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable, CouldNotRetrieveTranscript):
        logger.info("YouTube API not found, falling back to Whisper: %s", dest_path)
    except Exception:
        logger.exception("YouTube API error: %s", video_id)

    try:
        text = _whisper(dest_path)
        save_transcript_to_file(str(uuid.uuid4())[:8], {"engine": "whisper", "transcript": text})
        logger.info("Whisper fallback done: %s", dest_path)
        return jsonify({"status": "success", "engine": "whisper", "text": text})
    except Exception as e:
        logger.exception("Whisper fallback failed: %s", dest_path)
        return jsonify({"error": f"Transkript hatası: {str(e)}"}), 500


@app.route("/batch_transcribe", methods=["POST"])
def batch_transcribe():
    data = request.get_json()
    urls = data.get("urls", [])
    profile = data.get("profile", "")

    if not urls:
        return jsonify({"error": "URL listesi boş."}), 400

    results = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        platform = "instagram" if "instagram.com" in url else "youtube"
        entry = {"url": url, "platform": platform, "engine": None, "text": None, "status": "error", "error": None}

        try:
            dest_path = _download_mp3(url)
        except Exception as e:
            entry["error"] = f"İndirme hatası: {str(e)}"
            logger.exception("Batch download failed: %s", url)
            results.append(entry)
            continue

        if platform == "instagram":
            try:
                entry["text"] = _whisper(dest_path)
                entry["engine"] = "whisper"
                entry["status"] = "success"
            except Exception as e:
                entry["error"] = f"Whisper hatası: {str(e)}"
        else:
            video_id = extract_youtube_video_id(url)
            api_ok = False
            if video_id:
                try:
                    text, transcript = _youtube_api(video_id)
                    entry["text"] = text
                    entry["engine"] = "youtube_api"
                    entry["status"] = "success"
                    api_ok = True
                except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable, CouldNotRetrieveTranscript):
                    pass
                except Exception:
                    logger.exception("Batch YouTube API error: %s", video_id)

            if not api_ok:
                try:
                    entry["text"] = _whisper(dest_path)
                    entry["engine"] = "whisper"
                    entry["status"] = "success"
                except Exception as e:
                    entry["error"] = f"Whisper hatası: {str(e)}"

        results.append(entry)
        logger.info("Batch [%s/%s]: %s", len(results), len(urls), url)

    output = {
        "profile": profile,
        "processed_at": __import__("datetime").datetime.now().isoformat(),
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "results": results,
    }
    return jsonify(output)


if __name__ == "__main__":
    logger.info("Starting Flask development server")
    app.run(debug=True)
