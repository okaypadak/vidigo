import logging
import os
import queue
import shutil
import uuid
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

from transcribers.whisper_transcriber import transcribe_whisper
from utils.app_logging import (
    LOG_STREAM_HUB,
    bind_operation,
    configure_logging,
    log_exception,
    log_info,
    log_warning,
)
from utils.download_service import COOKIE_ROOT, batch_download_media, classify_download_url, download_media
from utils.file_utils import load_download_history, save_download_record, save_transcript_to_file, upsert_manifest_item
from utils.video_downloader import build_unique_filepath, download_audio_generic, extract_instagram_shortcode, resolve_cookie_file
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

configure_logging(LOG_PATH)
logger = logging.getLogger(__name__)


def _operation_id_from_request():
    return (
        (request.headers.get("X-Operation-Id") or "").strip()
        or (request.args.get("operation_id") or "").strip()
        or str(uuid.uuid4())[:8]
    )


def _json_response(payload, status=200, operation_id=None):
    response = jsonify(payload)
    response.status_code = status
    if operation_id:
        response.headers["X-Operation-Id"] = operation_id
    return response


def _plain_transcript(transcript):
    return "\n".join(
        (item.get("text") or "").strip()
        for item in transcript
        if (item.get("text") or "").strip()
    )


def _download_mp3(url, cookie_path=None):
    log_info(logger, "Ses dosyasi hazirlama basladi", stage="audio.prepare", url=url, work_dir=DOWNLOAD_DIR)
    downloaded_path = download_audio_generic(url, save_path=DOWNLOAD_DIR, cookie_path=cookie_path)
    filename = os.path.basename(downloaded_path)
    stem, extension = os.path.splitext(filename)
    dest_path = build_unique_filepath(AUDIO_DIR, stem, extension)
    shutil.move(downloaded_path, dest_path)
    log_info(
        logger,
        "Ses dosyasi calisma klasorune tasindi",
        stage="audio.prepare",
        source_path=downloaded_path,
        dest_path=dest_path,
    )
    return dest_path


def _whisper(dest_path):
    log_info(logger, "Whisper transkripsiyonu baslatiliyor", stage="transcribe.whisper", audio_path=dest_path)
    result = transcribe_whisper(dest_path)
    text = result if isinstance(result, str) else str(result)
    log_info(
        logger,
        "Whisper transkripsiyonu tamamlandi",
        stage="transcribe.whisper",
        audio_path=dest_path,
        text_length=len(text),
    )
    return text


def _youtube_api(video_id):
    log_info(logger, "YouTube transcript API denemesi basladi", stage="transcribe.youtube_api", video_id=video_id)
    api = YouTubeTranscriptApi()
    if hasattr(YouTubeTranscriptApi, "get_transcript"):
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
    else:
        fetched = api.fetch(video_id, languages=("tr", "en"))
        transcript = fetched.to_raw_data()
    log_info(
        logger,
        "YouTube transcript API yaniti alindi",
        stage="transcribe.youtube_api",
        video_id=video_id,
        line_count=len(transcript),
    )
    return _plain_transcript(transcript), transcript


def _video_name_from_path(path):
    return os.path.splitext(os.path.basename(path))[0]


def _persist_transcript(
    dest_path,
    url,
    platform,
    engine,
    text,
    video_id=None,
    transcript_payload=None,
):
    video_name = _video_name_from_path(dest_path)
    transcript_id = video_id or str(uuid.uuid4())[:8]
    log_info(
        logger,
        "Transkript kaydi hazirlaniyor",
        stage="persist.transcript",
        transcript_id=transcript_id,
        video_name=video_name,
        platform=platform,
        engine=engine,
    )
    payload = {
        "engine": engine,
        "platform": platform,
        "url": url,
        "video_name": video_name,
        "file_name": os.path.basename(dest_path),
        "file_path": dest_path,
        "text": text,
        "transcript": transcript_payload if transcript_payload is not None else text,
    }
    if video_id:
        payload["video_id"] = video_id

    save_transcript_to_file(transcript_id, payload)
    save_download_record(
        video_name=video_name,
        transcript=text,
        platform=platform,
        engine=engine,
        url=url,
        video_id=video_id,
        file_name=os.path.basename(dest_path),
        file_path=dest_path,
    )
    log_info(
        logger,
        "Transkript ve gecmis kaydi yazildi",
        stage="persist.transcript",
        transcript_id=transcript_id,
        file_name=os.path.basename(dest_path),
    )


def _save_transcript_file_only(dest_path, url, platform, engine, text, video_id=None):
    transcript_id = video_id or str(uuid.uuid4())[:8]
    payload = {
        "engine": engine,
        "platform": platform,
        "url": url,
        "video_name": _video_name_from_path(dest_path),
        "file_name": os.path.basename(dest_path),
        "file_path": dest_path,
        "text": text,
        "transcript": text,
    }
    if video_id:
        payload["video_id"] = video_id
    save_transcript_to_file(transcript_id, payload)
    return transcript_id


def _attach_item_transcripts(result):
    if result.get("status") != "success":
        return result

    items = result.get("items") or []
    if not items:
        return result

    platform = result.get("platform")
    source_type = result.get("source_type")
    source_name = result.get("source_name")
    source_url = result.get("source_url") or result.get("url")
    downloader = result.get("downloader")
    download_dir = result.get("download_dir")
    transcript_count = 0

    for item in items:
        file_path = item.get("file_path")
        if not file_path or not os.path.isfile(file_path):
            item["transcript_error"] = "Ses dosyasi bulunamadi."
            continue

        try:
            text = _whisper(file_path)
            item["engine"] = "whisper"
            item["transcript"] = text
            transcript_count += 1
            video_id = item.get("video_id") or item.get("shortcode") or item.get("id")
            _save_transcript_file_only(file_path, item.get("webpage_url") or item.get("source_url") or source_url, platform, "whisper", text, video_id=video_id)
            manifest_path, _ = upsert_manifest_item(
                platform,
                source_name,
                source_type,
                source_url,
                item,
                downloader=downloader,
                download_dir=download_dir,
                engine="whisper",
            )
            if manifest_path:
                result["manifest_path"] = manifest_path
        except Exception as exc:
            item["transcript_error"] = f"Whisper hatasi: {str(exc)}"
            log_exception(
                logger,
                "Batch download item transkripsiyonu basarisiz oldu",
                stage="batch.item.transcribe",
                url=item.get("webpage_url") or item.get("source_url") or source_url,
                file_path=file_path,
            )

    result["transcribed_count"] = transcript_count
    if transcript_count:
        result["engine"] = "whisper"
    return result


def _single_audio_payload(url, cookie_path=None):
    request = classify_download_url(url)
    if request["source_type"] not in {"video", "reel"}:
        return download_media(url, cookie_path=cookie_path)

    platform = request["platform"]
    source_type = request["source_type"]
    resolved_cookie = resolve_cookie_file(platform, cookie_path=cookie_path, cookie_dir=COOKIE_ROOT)
    dest_path = _download_mp3(url, cookie_path=cookie_path)
    text = _whisper(dest_path)
    video_id = extract_youtube_video_id(url) if platform == "youtube" else extract_instagram_shortcode(url)
    source_name = _video_name_from_path(dest_path)

    _persist_transcript(dest_path, url, platform, "whisper", text, video_id=video_id)

    item = {
        "id": video_id,
        "video_id": video_id,
        "shortcode": video_id if platform == "instagram" else None,
        "title": source_name,
        "platform": platform,
        "source_url": url,
        "webpage_url": url,
        "file_name": os.path.basename(dest_path),
        "file_path": dest_path,
        "downloaded_at": datetime.now().isoformat(),
        "engine": "whisper",
        "transcript": text,
    }
    manifest_path, _ = upsert_manifest_item(
        platform,
        source_name,
        source_type,
        url,
        item,
        downloader="audio+whisper",
        download_dir=os.path.dirname(dest_path),
        engine="whisper",
    )

    return {
        "platform": platform,
        "source_type": source_type,
        "source_name": source_name,
        "source_url": url,
        "download_dir": os.path.dirname(dest_path),
        "manifest_path": manifest_path,
        "cookie_file": resolved_cookie,
        "downloader": "audio+whisper",
        "engine": "whisper",
        "item_count": 1,
        "items": [item],
    }


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/history_page", methods=["GET"])
def history_page():
    return render_template("history.html")


@app.route("/status", methods=["GET"])
def status():
    try:
        import torch

        gpu_available = torch.cuda.is_available()
    except ImportError:
        gpu_available = False
    return jsonify({"gpu": gpu_available})


@app.route("/logs/stream", methods=["GET"])
def stream_logs():
    operation_id = (request.args.get("operation_id") or "").strip() or None
    subscriber_id, subscriber_queue, backlog = LOG_STREAM_HUB.subscribe(operation_id=operation_id)

    def generate():
        try:
            for line in backlog:
                yield f"data: {line}\n\n"

            while True:
                try:
                    line = subscriber_queue.get(timeout=15)
                    yield f"data: {line}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            LOG_STREAM_HUB.unsubscribe(subscriber_id)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/history", methods=["GET"])
def history():
    operation_id = _operation_id_from_request()
    try:
        with bind_operation(operation_id):
            limit = request.args.get("limit", type=int)
            log_info(logger, "Gecmis kaydi yukleme istegi alindi", stage="history.load", limit=limit)
            records = load_download_history(limit=limit)
            log_info(logger, "Gecmis kayitlari yuklendi", stage="history.load", record_count=len(records))
            return _json_response({"items": records, "total": len(records)}, operation_id=operation_id)
    except Exception as exc:
        with bind_operation(operation_id):
            log_exception(logger, "Gecmis kayitlari yuklenemedi", stage="history.load")
        return _json_response({"error": f"Gecmis yuklenemedi: {str(exc)}"}, status=500, operation_id=operation_id)


@app.route("/download_media", methods=["POST"])
def download_media_route():
    operation_id = _operation_id_from_request()
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    cookie_path = (data.get("cookie_path") or "").strip() or None

    if not url:
        return _json_response({"error": "Indirilecek URL gerekli."}, status=400, operation_id=operation_id)

    try:
        with bind_operation(operation_id):
            log_info(logger, "Tekli indirme istegi alindi", stage="request.accepted", url=url, cookie_path=cookie_path or "auto")
            payload = _single_audio_payload(url, cookie_path=cookie_path)
            log_info(
                logger,
                "Tekli indirme istegi tamamlandi",
                stage="request.completed",
                url=url,
                item_count=payload.get("item_count", 0),
            )
            return _json_response({"status": "success", **payload}, operation_id=operation_id)
    except ValueError as exc:
        with bind_operation(operation_id):
            log_warning(logger, "Gecersiz indirme istegi", stage="request.validation", url=url, error=str(exc))
        return _json_response({"error": str(exc)}, status=400, operation_id=operation_id)
    except Exception as exc:
        with bind_operation(operation_id):
            log_exception(logger, "Tekli indirme akisi basarisiz oldu", stage="request.failed", url=url)
        return _json_response({"error": f"Indirme hatasi: {str(exc)}"}, status=500, operation_id=operation_id)


@app.route("/batch_download", methods=["POST"])
def batch_download_route():
    operation_id = _operation_id_from_request()
    data = request.get_json(silent=True) or {}
    urls = data.get("urls", [])
    cookie_path = (data.get("cookie_path") or "").strip() or None

    if not urls:
        return _json_response({"error": "URL listesi bos."}, status=400, operation_id=operation_id)

    try:
        with bind_operation(operation_id):
            log_info(
                logger,
                "Toplu indirme istegi alindi",
                stage="request.accepted",
                total_urls=len(urls),
                cookie_path=cookie_path or "auto",
            )
            payload = batch_download_media(urls, cookie_path=cookie_path)
            payload["results"] = [_attach_item_transcripts(result) for result in payload.get("results", [])]
            log_info(
                logger,
                "Toplu indirme tamamlandi",
                stage="request.completed",
                success=payload.get("success"),
                total=payload.get("total"),
            )
            return _json_response(payload, operation_id=operation_id)
    except Exception as exc:
        with bind_operation(operation_id):
            log_exception(logger, "Toplu indirme akisi basarisiz oldu", stage="request.failed")
        return _json_response({"error": f"Toplu indirme hatasi: {str(exc)}"}, status=500, operation_id=operation_id)


@app.route("/instagram_transcribe", methods=["POST"])
def instagram_transcribe():
    operation_id = _operation_id_from_request()
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url or "instagram.com" not in url:
        return _json_response({"error": "Gecerli bir Instagram URL girin."}, status=400, operation_id=operation_id)

    try:
        with bind_operation(operation_id):
            log_info(logger, "Instagram transkripsiyon istegi alindi", stage="request.accepted", url=url)
            dest_path = _download_mp3(url)
    except Exception as exc:
        with bind_operation(operation_id):
            log_exception(logger, "Instagram icin ses hazirlama basarisiz oldu", stage="request.failed", url=url)
        return _json_response({"error": f"Indirme hatasi: {str(exc)}"}, status=500, operation_id=operation_id)

    try:
        with bind_operation(operation_id):
            text = _whisper(dest_path)
            _persist_transcript(dest_path, url, "instagram", "whisper", text)
            log_info(logger, "Instagram transkripsiyonu tamamlandi", stage="request.completed", audio_path=dest_path)
            return _json_response({"status": "success", "engine": "whisper", "text": text}, operation_id=operation_id)
    except Exception as exc:
        with bind_operation(operation_id):
            log_exception(logger, "Instagram Whisper transkripsiyonu basarisiz oldu", stage="request.failed", audio_path=dest_path)
        return _json_response({"error": f"Transkript hatasi: {str(exc)}"}, status=500, operation_id=operation_id)


@app.route("/youtube_transcribe", methods=["POST"])
def youtube_transcribe():
    operation_id = _operation_id_from_request()
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    video_id = extract_youtube_video_id(url)
    if not video_id:
        return _json_response({"error": "Gecerli bir YouTube URL girin."}, status=400, operation_id=operation_id)

    try:
        with bind_operation(operation_id):
            log_info(logger, "YouTube transkripsiyon istegi alindi", stage="request.accepted", url=url, video_id=video_id)
            dest_path = _download_mp3(url)
    except Exception as exc:
        with bind_operation(operation_id):
            log_exception(logger, "YouTube icin ses hazirlama basarisiz oldu", stage="request.failed", url=url)
        return _json_response({"error": f"Indirme hatasi: {str(exc)}"}, status=500, operation_id=operation_id)

    try:
        with bind_operation(operation_id):
            text, transcript = _youtube_api(video_id)
            _persist_transcript(
                dest_path,
                url,
                "youtube",
                "youtube_api",
                text,
                video_id=video_id,
                transcript_payload=transcript,
            )
            log_info(logger, "YouTube transcript API ile transkript bulundu", stage="request.completed", video_id=video_id)
            return _json_response({"status": "success", "engine": "youtube_api", "text": text}, operation_id=operation_id)
    except (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
        CouldNotRetrieveTranscript,
    ):
        with bind_operation(operation_id):
            log_info(
                logger,
                "YouTube transcript API sonuc vermedi, Whisper'a geciliyor",
                stage="transcribe.fallback",
                audio_path=dest_path,
                video_id=video_id,
            )
    except Exception:
        with bind_operation(operation_id):
            log_exception(logger, "YouTube transcript API beklenmeyen hata verdi", stage="transcribe.youtube_api", video_id=video_id)

    try:
        with bind_operation(operation_id):
            text = _whisper(dest_path)
            _persist_transcript(dest_path, url, "youtube", "whisper", text, video_id=video_id)
            log_info(logger, "Whisper fallback tamamlandi", stage="request.completed", audio_path=dest_path, video_id=video_id)
            return _json_response({"status": "success", "engine": "whisper", "text": text}, operation_id=operation_id)
    except Exception as exc:
        with bind_operation(operation_id):
            log_exception(logger, "Whisper fallback basarisiz oldu", stage="request.failed", audio_path=dest_path, video_id=video_id)
        return _json_response({"error": f"Transkript hatasi: {str(exc)}"}, status=500, operation_id=operation_id)


@app.route("/batch_transcribe", methods=["POST"])
def batch_transcribe():
    operation_id = _operation_id_from_request()
    data = request.get_json(silent=True) or {}
    urls = data.get("urls", [])
    profile = data.get("profile", "")

    if not urls:
        return _json_response({"error": "URL listesi bos."}, status=400, operation_id=operation_id)

    with bind_operation(operation_id):
        log_info(logger, "Toplu transkripsiyon istegi alindi", stage="request.accepted", total_urls=len(urls), profile=profile or "-")
        results = []
        for index, url in enumerate(urls, start=1):
            url = url.strip()
            if not url:
                continue

            platform = "instagram" if "instagram.com" in url else "youtube"
            entry = {
                "url": url,
                "platform": platform,
                "engine": None,
                "text": None,
                "status": "error",
                "error": None,
            }
            log_info(logger, "Toplu transkripsiyon girdisi isleniyor", stage="batch.item.start", index=index, total=len(urls), url=url, platform=platform)

            try:
                dest_path = _download_mp3(url)
            except Exception as exc:
                entry["error"] = f"Indirme hatasi: {str(exc)}"
                log_exception(logger, "Toplu transkripsiyon icin ses hazirlama basarisiz oldu", stage="batch.item.download", url=url)
                results.append(entry)
                continue

            if platform == "instagram":
                try:
                    entry["text"] = _whisper(dest_path)
                    entry["engine"] = "whisper"
                    entry["status"] = "success"
                    _persist_transcript(dest_path, url, platform, entry["engine"], entry["text"])
                except Exception as exc:
                    entry["error"] = f"Whisper hatasi: {str(exc)}"
                    log_exception(logger, "Instagram batch Whisper basarisiz oldu", stage="batch.item.transcribe", url=url, audio_path=dest_path)
            else:
                video_id = extract_youtube_video_id(url)
                api_ok = False

                if video_id:
                    try:
                        text, transcript = _youtube_api(video_id)
                        entry["text"] = text
                        entry["engine"] = "youtube_api"
                        entry["status"] = "success"
                        _persist_transcript(
                            dest_path,
                            url,
                            platform,
                            entry["engine"],
                            entry["text"],
                            video_id=video_id,
                            transcript_payload=transcript,
                        )
                        api_ok = True
                    except (
                        NoTranscriptFound,
                        TranscriptsDisabled,
                        VideoUnavailable,
                        CouldNotRetrieveTranscript,
                    ):
                        log_info(logger, "Batch YouTube transcript API sonuc vermedi, Whisper'a geciliyor", stage="batch.item.fallback", video_id=video_id, url=url)
                    except Exception:
                        log_exception(logger, "Batch YouTube transcript API beklenmeyen hata verdi", stage="batch.item.youtube_api", video_id=video_id, url=url)

                if not api_ok:
                    try:
                        entry["text"] = _whisper(dest_path)
                        entry["engine"] = "whisper"
                        entry["status"] = "success"
                        _persist_transcript(
                            dest_path,
                            url,
                            platform,
                            entry["engine"],
                            entry["text"],
                            video_id=video_id,
                        )
                    except Exception as exc:
                        entry["error"] = f"Whisper hatasi: {str(exc)}"
                        log_exception(logger, "Batch Whisper transkripsiyonu basarisiz oldu", stage="batch.item.transcribe", url=url, audio_path=dest_path)

            results.append(entry)
            log_info(
                logger,
                "Toplu transkripsiyon girdisi tamamlandi",
                stage="batch.item.done",
                index=len(results),
                total=len(urls),
                url=url,
                status=entry["status"],
                engine=entry["engine"] or "-",
            )

        output = {
            "profile": profile,
            "processed_at": __import__("datetime").datetime.now().isoformat(),
            "total": len(results),
            "success": sum(1 for result in results if result["status"] == "success"),
            "results": results,
        }
        log_info(logger, "Toplu transkripsiyon tamamlandi", stage="request.completed", success=output["success"], total=output["total"])
        return _json_response(output, operation_id=operation_id)


if __name__ == "__main__":
    log_info(logger, "Flask gelistirme sunucusu baslatiliyor", stage="startup", host="127.0.0.1", port=5000)
    app.run(debug=True)
