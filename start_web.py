import logging
import os
import queue
import shutil
import time
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
from utils.download_service import COOKIE_ROOT, classify_download_url
from utils.file_utils import load_download_history, save_download_record, save_transcript_to_file, upsert_download_record, upsert_manifest_item
from utils.video_downloader import build_unique_filepath, download_audio_generic, download_youtube_transcript_ytdlp, extract_instagram_shortcode, list_youtube_video_urls, resolve_cookie_file, sanitize_filename
from utils.youtube_utils import extract_youtube_channel_name, extract_youtube_video_id

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
YOUTUBE_TRANSCRIPT_DELAY_SECONDS = 5
YOUTUBE_TRANSCRIPT_RETRY_SECONDS = (5, 10)
_last_youtube_transcript_request_at = 0.0


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


def _normalize_audio_path(downloaded_path, folder_name=None):
    current_dir = os.path.dirname(downloaded_path)
    account_name = folder_name or _folder_name_from_path(downloaded_path) or "unknown"
    target_dir = os.path.join(AUDIO_DIR, account_name, "ses")
    current_abs = os.path.abspath(current_dir)
    target_abs = os.path.abspath(target_dir)
    if current_abs == target_abs:
        return downloaded_path

    stem, extension = os.path.splitext(os.path.basename(downloaded_path))
    target_path = build_unique_filepath(target_dir, stem, extension)
    shutil.move(downloaded_path, target_path)
    log_info(
        logger,
        "Ses dosyasi hedef klasore tasindi",
        stage="audio.prepare",
        source_path=downloaded_path,
        target_path=target_path,
        account_name=account_name,
    )
    return target_path


def _ytdlp_transcript_dir(source_name=None):
    safe_name = sanitize_filename(source_name) if source_name else "unknown"
    path = os.path.join(AUDIO_DIR, safe_name, "transcript")
    os.makedirs(path, exist_ok=True)
    return path


def _download_mp3(url, cookie_path=None, folder_name=None):
    os.makedirs(AUDIO_DIR, exist_ok=True)
    log_info(logger, "Ses dosyasi hazirlama basladi", stage="audio.prepare", url=url, target_root=AUDIO_DIR)
    downloaded_path = download_audio_generic(url, save_path=AUDIO_DIR, cookie_path=cookie_path)
    return _normalize_audio_path(downloaded_path, folder_name=folder_name)


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
    global _last_youtube_transcript_request_at

    attempts = len(YOUTUBE_TRANSCRIPT_RETRY_SECONDS) + 1
    for attempt in range(1, attempts + 1):
        elapsed = time.monotonic() - _last_youtube_transcript_request_at
        if elapsed < YOUTUBE_TRANSCRIPT_DELAY_SECONDS:
            wait_seconds = YOUTUBE_TRANSCRIPT_DELAY_SECONDS - elapsed
            log_info(
                logger,
                "YouTube transcript API hiz siniri bekleniyor",
                stage="transcribe.youtube_api",
                video_id=video_id,
                wait_seconds=round(wait_seconds, 1),
            )
            time.sleep(wait_seconds)

        log_info(logger, "YouTube transcript API denemesi basladi", stage="transcribe.youtube_api", video_id=video_id, attempt=attempt)
        _last_youtube_transcript_request_at = time.monotonic()
        try:
            api = YouTubeTranscriptApi()
            if hasattr(YouTubeTranscriptApi, "get_transcript"):
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["tr", "en"])
            else:
                fetched = api.fetch(video_id, languages=("tr", "en"))
                transcript = fetched.to_raw_data()
            log_info(
                logger,
                "YouTube transcript API yaniti alindi",
                stage="transcribe.youtube_api",
                video_id=video_id,
                line_count=len(transcript),
                attempt=attempt,
            )
            return _plain_transcript(transcript), transcript
        except (
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
        ):
            raise
        except Exception:
            if attempt >= attempts:
                raise
            wait_seconds = YOUTUBE_TRANSCRIPT_RETRY_SECONDS[attempt - 1]
            log_warning(
                logger,
                "YouTube transcript API gecici hata verdi, tekrar denenecek",
                stage="transcribe.youtube_api",
                video_id=video_id,
                attempt=attempt,
                wait_seconds=wait_seconds,
            )
            time.sleep(wait_seconds)


def _video_name_from_path(path):
    return os.path.splitext(os.path.basename(path))[0]


def _folder_name_from_path(path):
    parent = os.path.basename(os.path.dirname(path or ""))
    if parent == "ses":
        parent = os.path.basename(os.path.dirname(os.path.dirname(path or "")))
    return parent if parent and parent not in {"audiofiles", "downloads", "ses", "transcript"} else None


def _persist_transcript(
    dest_path,
    url,
    platform,
    engine,
    text,
    video_id=None,
    transcript_payload=None,
    file_path=None,
    audio_removed=False,
    uploader=None,
):
    video_name = _video_name_from_path(dest_path)
    transcript_id = video_id or str(uuid.uuid4())[:8]
    stored_file_path = dest_path if file_path is None and not audio_removed else file_path
    folder_name = uploader or _folder_name_from_path(dest_path)
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
        "uploader": folder_name,
        "file_name": os.path.basename(dest_path),
        "file_path": stored_file_path,
        "removed_file_path": dest_path if audio_removed else None,
        "text": text,
        "transcript": transcript_payload if transcript_payload is not None else text,
    }
    if audio_removed:
        payload["audio_removed"] = True
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
        file_path=stored_file_path,
        removed_file_path=dest_path if audio_removed else None,
        uploader=folder_name,
        audio_removed=audio_removed,
    )
    log_info(
        logger,
        "Transkript ve gecmis kaydi yazildi",
        stage="persist.transcript",
        transcript_id=transcript_id,
        file_name=os.path.basename(dest_path),
    )


def _save_transcript_file_only(dest_path, url, platform, engine, text, video_id=None, uploader=None):
    transcript_id = video_id or str(uuid.uuid4())[:8]
    payload = {
        "engine": engine,
        "platform": platform,
        "url": url,
        "video_name": _video_name_from_path(dest_path),
        "uploader": uploader or _folder_name_from_path(dest_path),
        "file_name": os.path.basename(dest_path),
        "file_path": dest_path,
        "text": text,
        "transcript": text,
    }
    if video_id:
        payload["video_id"] = video_id
    save_transcript_to_file(transcript_id, payload)
    return transcript_id


def _persist_downloaded_item(item, *, platform, source_type, source_name, source_url, download_dir, downloader):
    file_path = item.get("file_path")
    if not file_path or not os.path.isfile(file_path):
        item["transcript_error"] = "Ses dosyasi bulunamadi."
        return None

    if item.get("transcript") and item.get("engine"):
        return item.get("manifest_path")

    item_url = item.get("webpage_url") or item.get("source_url") or source_url
    video_id = item.get("video_id") or item.get("shortcode") or item.get("id")

    try:
        text = _whisper(file_path)
        item["engine"] = "whisper"
        item["transcript"] = text
    except Exception as exc:
        item["transcript_error"] = f"Whisper hatasi: {str(exc)}"
        log_exception(
            logger,
            "Indirilen oge aninda transkribe edilemedi",
            stage="batch.item.transcribe",
            url=item_url,
            file_path=file_path,
        )
        return None

    try:
        _save_transcript_file_only(file_path, item_url, platform, "whisper", text, video_id=video_id, uploader=item.get("uploader"))
        log_info(
            logger,
            "Transkript dosyasi yazildi",
            stage="batch.item.save",
            file_path=file_path,
            transcript_id=video_id or "-",
        )
    except Exception:
        log_exception(logger, "Transkript dosyasi kaydedilemedi", stage="batch.item.save", file_path=file_path)

    manifest_path = None
    try:
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
            item["manifest_path"] = manifest_path
            log_info(logger, "Manifest guncellendi", stage="batch.item.manifest", file_path=file_path, manifest_path=manifest_path)
    except Exception:
        log_exception(logger, "Manifest guncellenemedi", stage="batch.item.manifest", file_path=file_path)

    try:
        upsert_download_record(
            video_name=_video_name_from_path(file_path),
            transcript=text,
            platform=platform,
            source_type=source_type,
            source_name=source_name,
            source_url=source_url,
            engine="whisper",
            url=item_url,
            video_id=video_id,
            shortcode=item.get("shortcode"),
            file_name=os.path.basename(file_path),
            file_path=file_path,
            uploader=item.get("uploader"),
            downloader=downloader,
            manifest_path=manifest_path,
        )
        log_info(
            logger,
            "TinyDB kaydi yazildi",
            stage="batch.item.db",
            file_path=file_path,
            video_id=video_id or "-",
        )
    except Exception:
        log_exception(logger, "TinyDB kaydi guncellenemedi", stage="batch.item.db", file_path=file_path)

    log_info(
        logger,
        "Tekil indirme zinciri tamamlandi",
        stage="batch.item.done",
        url=item_url,
        file_path=file_path,
        video_id=video_id or "-",
    )
    return manifest_path


def _transcribe_downloaded_audio(platform, dest_path, url, video_id):
    if platform == "youtube":
        text, transcript = _youtube_api(video_id)
        return "youtube_api", text, transcript
    return "whisper", _whisper(dest_path), None


def _process_audio_item(url, *, cookie_path=None, mode="download", source_type=None, source_name=None, source_url=None, item_hint=None):
    transcript_enabled = mode in {"download", "transcript_only"}
    keep_audio_files = mode in {"download", "mp3_only"}
    request = classify_download_url(url)
    platform = request["platform"]
    item_source_type = source_type or request["source_type"]
    item_source_url = source_url or url
    resolved_cookie = resolve_cookie_file(platform, cookie_path=cookie_path, cookie_dir=COOKIE_ROOT)

    hint_folder = (item_hint or {}).get("uploader") or source_name

    # YouTube + transcript_only → ses indirmeden yt-dlp subtitle kullan
    if mode == "transcript_only" and platform == "youtube":
        source_name_for_dir = hint_folder or extract_youtube_channel_name(url) or None
        transcript_dir = _ytdlp_transcript_dir(source_name_for_dir)
        txt_items = download_youtube_transcript_ytdlp(url, save_path=transcript_dir, cookie_path=resolved_cookie)
        if not txt_items:
            raise FileNotFoundError("YouTube altyazısı bulunamadı. Video için altyazı mevcut olmayabilir.")
        manifest_path = None
        result_items = []
        for txt_item in txt_items:
            txt_path = txt_item.get("txt_path")
            if not txt_path or not os.path.isfile(txt_path):
                continue
            video_name = os.path.splitext(os.path.basename(txt_path))[0]
            text = open(txt_path, encoding="utf-8").read()
            item_data = {
                "id": None, "video_id": None, "shortcode": None,
                "title": video_name, "platform": "youtube",
                "uploader": source_name_for_dir, "source_url": url, "webpage_url": url,
                "file_name": os.path.basename(txt_path), "file_path": txt_path,
                "downloaded_at": datetime.now().isoformat(),
                "engine": "ytdlp_subtitle", "transcript": text,
            }
            try:
                mp, _ = upsert_manifest_item("youtube", source_name_for_dir or video_name, item_source_type, item_source_url, item_data, downloader="yt-dlp", download_dir=transcript_dir, engine="ytdlp_subtitle")
                item_data["manifest_path"] = mp
                manifest_path = mp or manifest_path
            except Exception:
                log_exception(logger, "Transcript manifest yazilamadi", stage="transcript.manifest", txt_path=txt_path)
            try:
                upsert_download_record(video_name=video_name, transcript=text, platform="youtube", source_type=item_source_type, source_name=source_name_for_dir or video_name, source_url=item_source_url, engine="ytdlp_subtitle", url=url, file_name=os.path.basename(txt_path), file_path=txt_path, uploader=source_name_for_dir, downloader="yt-dlp", manifest_path=manifest_path)
            except Exception:
                log_exception(logger, "Transcript DB kaydi yazilamadi", stage="transcript.db", txt_path=txt_path)
            result_items.append(item_data)
        first = result_items[0] if result_items else {"title": "transcript", "platform": "youtube", "engine": "ytdlp_subtitle"}
        return first, manifest_path, resolved_cookie

    dest_path = _download_mp3(url, cookie_path=resolved_cookie, folder_name=hint_folder)
    video_id = extract_youtube_video_id(url) if platform == "youtube" else extract_instagram_shortcode(url)
    title = _video_name_from_path(dest_path)
    uploader = (item_hint or {}).get("uploader") or _folder_name_from_path(dest_path)
    item_source_name = source_name or uploader or title

    engine = None
    text = None
    transcript_payload = None
    transcript_error = None
    if transcript_enabled:
        if platform == "youtube":
            # Önce yt-dlp subtitle dene, olmazsa YouTube API'ye fallback
            try:
                audio_dir = os.path.dirname(dest_path)
                parent_dir = os.path.dirname(audio_dir) if os.path.basename(audio_dir).lower() == "ses" else audio_dir
                tr_dir = os.path.join(parent_dir, "transcript")
                os.makedirs(tr_dir, exist_ok=True)
                txt_items = download_youtube_transcript_ytdlp(url, save_path=tr_dir, cookie_path=resolved_cookie)
                if txt_items:
                    txt_path = txt_items[0].get("txt_path")
                    text = open(txt_path, encoding="utf-8").read() if txt_path and os.path.isfile(txt_path) else None
                    engine = "ytdlp_subtitle"
                    log_info(logger, "yt-dlp subtitle ile transcript alindi", stage="transcribe.item", url=url)
            except Exception:
                log_exception(logger, "yt-dlp subtitle basarisiz, API fallback deneniyor", stage="transcribe.item", url=url)
            if not text and video_id:
                try:
                    log_info(logger, "YouTube API ile transcript deneniyor", stage="transcribe.item", video_id=video_id)
                    _, text, transcript_payload = _transcribe_downloaded_audio(platform, dest_path, url, video_id)
                    engine = "youtube_api"
                except Exception as exc:
                    transcript_error = f"Transkript hatasi: {str(exc)}"
                    engine = "error"
                    text = transcript_error
                    log_exception(logger, "YouTube API de basarisiz oldu", stage="transcribe.item", url=url)
        else:
            try:
                engine, text, transcript_payload = _transcribe_downloaded_audio(platform, dest_path, url, video_id)
            except Exception as exc:
                transcript_error = f"Transkript hatasi: {str(exc)}"
                engine = "error"
                text = transcript_error
                log_exception(logger, "Tekil transkript islemi basarisiz oldu", stage="transcribe.item", url=url, audio_path=dest_path)

    audio_removed = False
    if not keep_audio_files and os.path.isfile(dest_path):
        os.remove(dest_path)
        audio_removed = True

    item = {
        "id": video_id,
        "video_id": video_id,
        "shortcode": video_id if platform == "instagram" else None,
        "title": (item_hint or {}).get("title") or title,
        "platform": platform,
        "uploader": uploader,
        "source_url": url,
        "webpage_url": url,
        "file_name": os.path.basename(dest_path),
        "file_path": None if audio_removed else dest_path,
        "downloaded_at": datetime.now().isoformat(),
        "engine": engine,
        "transcript": text,
    }
    if transcript_error:
        item["transcript_error"] = transcript_error
    if audio_removed:
        item["audio_removed"] = True
        item["removed_file_path"] = dest_path

    if transcript_enabled and text:
        _persist_transcript(
            dest_path,
            url,
            platform,
            engine,
            text,
            video_id=video_id,
            transcript_payload=transcript_payload,
            file_path=None if audio_removed else dest_path,
            audio_removed=audio_removed,
            uploader=uploader,
        )

    manifest_path, _ = upsert_manifest_item(
        platform,
        item_source_name,
        item_source_type,
        item_source_url,
        item,
        downloader="audio+transcript" if transcript_enabled else "audio",
        download_dir=os.path.dirname(dest_path),
        engine=engine,
    )
    upsert_download_record(
        video_name=title,
        transcript=text,
        platform=platform,
        source_type=item_source_type,
        source_name=item_source_name,
        source_url=item_source_url,
        engine=engine,
        url=url,
        video_id=video_id,
        shortcode=item.get("shortcode"),
        file_name=os.path.basename(dest_path),
        file_path=None if audio_removed else dest_path,
        removed_file_path=dest_path if audio_removed else None,
        audio_removed=audio_removed,
        uploader=uploader,
        downloader="audio+transcript" if transcript_enabled else "audio",
        manifest_path=manifest_path,
    )
    item["manifest_path"] = manifest_path
    return item, manifest_path, resolved_cookie


def _expand_source_items(url, cookie_path=None):
    request = classify_download_url(url)
    if request["platform"] == "youtube" and request["source_type"] in {"playlist", "channel"}:
        resolved_cookie = resolve_cookie_file("youtube", cookie_path=cookie_path, cookie_dir=COOKIE_ROOT)
        return request, list_youtube_video_urls(url, cookie_path=resolved_cookie)
    return request, [{"url": url}]


def _attach_item_transcripts(result):
    if result.get("status") not in (None, "success"):
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

        if item.get("transcript") and item.get("engine"):
            transcript_count += 1
            if item.get("manifest_path"):
                result["manifest_path"] = item["manifest_path"]
            continue

        try:
            manifest_path = _persist_downloaded_item(
                item,
                platform=platform,
                source_type=source_type,
                source_name=source_name,
                source_url=source_url,
                download_dir=download_dir,
                downloader=downloader,
            )
            transcript_count += 1
            if manifest_path:
                result["manifest_path"] = manifest_path
        except Exception:
            log_exception(logger, "Batch item persistence beklenmeyen hata verdi", stage="batch.item.persist", file_path=file_path)
            continue

    result["transcribed_count"] = transcript_count
    if transcript_count:
        result["engine"] = "whisper"
    return result


def _already_downloaded(video_id, mode):
    """video_id için gerekli dosyalar zaten indirildiyse True döner."""
    from tinydb import Query
    from utils.file_utils import download_db, _DB_LOCK
    with _DB_LOCK:
        Q = Query()
        results = download_db.search(Q.video_id == video_id)
    if not results:
        return False
    record = results[0]
    needs_audio = mode in {"download", "mp3_only"}
    needs_transcript = mode in {"download", "transcript_only"}
    if needs_audio:
        file_path = record.get("file_path")
        if not file_path or not os.path.isfile(file_path):
            return False
    if needs_transcript:
        if not record.get("transcript"):
            return False
    return True


def _single_audio_payload(url, cookie_path=None, mode="download"):
    transcript_enabled = mode in {"download", "transcript_only"}
    request, source_items = _expand_source_items(url, cookie_path=cookie_path)
    if not source_items:
        raise FileNotFoundError("Islenecek video bulunamadi.")
    if request["platform"] == "instagram" and request["source_type"] == "profile_reels":
        raise ValueError("Instagram profil toplu akisi henuz tekil URL listesine acilmiyor. Reel URL'lerini tek tek verin.")

    items = []
    manifest_path = None
    cookie_file = None
    engine = None
    source_name = extract_youtube_channel_name(url) if request["source_type"] == "channel" else None
    download_dir = None
    transcribed_count = 0

    for index, source_item in enumerate(source_items, start=1):
        item_url = source_item.get("url")
        if not item_url:
            continue

        # Zaten indirilmişse atla
        video_id = source_item.get("video_id")
        if video_id and _already_downloaded(video_id, mode):
            log_info(logger, "Video zaten indirilmis, atlaniyor", stage="single.pipeline", index=index, total=len(source_items), video_id=video_id)
            continue

        log_info(
            logger,
            "Ortak tekil akista oge isleniyor",
            stage="single.pipeline",
            index=index,
            total=len(source_items),
            url=item_url,
        )
        item, item_manifest_path, item_cookie_file = _process_audio_item(
            item_url,
            cookie_path=cookie_path,
            mode=mode,
            source_type=request["source_type"],
            source_name=source_name,
            source_url=url,
            item_hint=source_item,
        )
        items.append(item)
        manifest_path = item_manifest_path or manifest_path
        cookie_file = item_cookie_file or cookie_file
        engine = item.get("engine") or engine
        source_name = source_name or item.get("uploader") or item.get("title")
        download_dir = download_dir or os.path.dirname(item.get("file_path") or item.get("removed_file_path") or "")
        if item.get("transcript"):
            transcribed_count += 1

    return {
        "platform": request["platform"],
        "source_type": request["source_type"],
        "source_name": source_name or url,
        "source_url": url,
        "download_dir": download_dir,
        "manifest_path": manifest_path,
        "cookie_file": cookie_file,
        "downloader": "audio+transcript" if transcript_enabled else "audio",
        "engine": engine,
        "item_count": len(items),
        "transcribed_count": transcribed_count,
        "items": items,
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
    mode = (data.get("mode") or "download").strip()

    if not url:
        return _json_response({"error": "Indirilecek URL gerekli."}, status=400, operation_id=operation_id)

    try:
        with bind_operation(operation_id):
            log_info(logger, "Tekli indirme istegi alindi", stage="request.accepted", url=url, cookie_path=cookie_path or "auto")
            if mode not in {"download", "mp3_only", "transcript_only"}:
                raise ValueError("Gecersiz mod. 'download', 'mp3_only' veya 'transcript_only' olmali.")
            payload = _single_audio_payload(url, cookie_path=cookie_path, mode=mode)
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
    ) as exc:
        with bind_operation(operation_id):
            log_warning(logger, "YouTube transcript API sonuc vermedi", stage="transcribe.youtube_api", audio_path=dest_path, video_id=video_id, error=str(exc))
        return _json_response({"error": f"YouTube transcript API hatasi: {str(exc)}"}, status=502, operation_id=operation_id)
    except Exception as exc:
        with bind_operation(operation_id):
            log_exception(logger, "YouTube transcript API beklenmeyen hata verdi", stage="transcribe.youtube_api", video_id=video_id)
        return _json_response({"error": f"YouTube transcript API hatasi: {str(exc)}"}, status=502, operation_id=operation_id)


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
                    ) as exc:
                        entry["error"] = f"YouTube transcript API hatasi: {str(exc)}"
                        log_warning(logger, "Batch YouTube transcript API sonuc vermedi", stage="batch.item.youtube_api", video_id=video_id, url=url, error=str(exc))
                    except Exception as exc:
                        entry["error"] = f"YouTube transcript API hatasi: {str(exc)}"
                        log_exception(logger, "Batch YouTube transcript API beklenmeyen hata verdi", stage="batch.item.youtube_api", video_id=video_id, url=url)

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
    debug_enabled = os.environ.get("VIDIGO_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    log_info(
        logger,
        "Flask sunucusu baslatiliyor",
        stage="startup",
        host="127.0.0.1",
        port=5000,
        debug=debug_enabled,
    )
    app.run(host="127.0.0.1", port=5000, debug=debug_enabled)
