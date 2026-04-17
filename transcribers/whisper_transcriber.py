import logging
import os
import warnings

import torch
import whisper

from utils.app_logging import log_exception, log_info
from utils.ffmpeg_utils import get_ffmpeg_binary

logger = logging.getLogger(__name__)


def _ensure_ffmpeg_available():
    """
    Whisper relies on ffmpeg being discoverable. Point it to the bundled binary
    and ensure PATH includes the ffmpeg directory when present.
    """
    ffmpeg_bin = get_ffmpeg_binary()
    os.environ.setdefault("FFMPEG_BINARY", ffmpeg_bin)

    ffmpeg_dir = os.path.dirname(ffmpeg_bin)
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    log_info(logger, "Whisper icin ffmpeg ortami hazirlandi", stage="whisper.prepare", ffmpeg_bin=ffmpeg_bin, ffmpeg_dir=ffmpeg_dir or "PATH")


def _format_timestamp(seconds):
    total_ms = max(int(round(float(seconds) * 1000)), 0)
    hours, remainder = divmod(total_ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"
    return f"{minutes:02}:{secs:02}.{millis:03}"


def transcribe_whisper(audio_path, lang="tr", model_path="medium"):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        try:
            _ensure_ffmpeg_available()
            log_info(logger, "Whisper modeli yukleniyor", stage="whisper.model", model_path=model_path, language=lang)
            model = whisper.load_model(model_path)
            log_info(logger, "Whisper modeli yuklendi", stage="whisper.model", model_path=model_path)
        except Exception:
            log_exception(logger, "Whisper modeli yuklenemedi", stage="whisper.model", model_path=model_path)
            return "Model yuklenemedi"

        try:
            use_cuda = torch.cuda.is_available()
            device = "cuda" if use_cuda else "cpu"
            log_info(logger, "Whisper transkripsiyonu calistiriliyor", stage="whisper.transcribe", audio_path=audio_path, device=device, language=lang)
            if use_cuda:
                model = model.to("cuda")
                result = model.transcribe(audio_path, language=lang, fp16=True)
            else:
                result = model.transcribe(audio_path, language=lang, fp16=False)

            segments = result.get("segments", [])
            lines = [seg["text"].strip() for seg in segments if seg["text"].strip()]
            first_segment = segments[0] if segments else None
            last_segment = segments[-1] if segments else None
            log_info(
                logger,
                "Whisper transkripsiyonu bitti",
                stage="whisper.transcribe",
                audio_path=audio_path,
                segment_count=len(segments),
                first_range=(
                    f"{_format_timestamp(first_segment['start'])}-{_format_timestamp(first_segment['end'])}"
                    if first_segment
                    else "-"
                ),
                last_range=(
                    f"{_format_timestamp(last_segment['start'])}-{_format_timestamp(last_segment['end'])}"
                    if last_segment
                    else "-"
                ),
            )
            return " ".join(lines).strip()
        except Exception as exc:
            log_exception(logger, "Whisper transkripsiyonu hata verdi", stage="whisper.transcribe", audio_path=audio_path)
            return f"Transkripsiyon hatasi: {str(exc)}"
