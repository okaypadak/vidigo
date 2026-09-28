import logging
import os
import warnings

import torch
import whisper

from utils.app_logging import log_exception, log_info
from utils.ffmpeg_utils import get_ffmpeg_binary

logger = logging.getLogger(__name__)


def _ensure_ffmpeg_available():
    ffmpeg_bin = get_ffmpeg_binary()
    if not ffmpeg_bin:
        raise FileNotFoundError("Whisper icin FFmpeg bulunamadi.")
    os.environ.setdefault("FFMPEG_BINARY", ffmpeg_bin)
    ffmpeg_dir = os.path.dirname(ffmpeg_bin)
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


def transcribe_whisper(audio_path, lang="tr", model_path="medium"):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            _ensure_ffmpeg_available()
            log_info(logger, "Whisper modeli yukleniyor", stage="whisper.model", model_path=model_path, language=lang)
            model = whisper.load_model(model_path)
        except Exception as exc:
            log_exception(logger, "Whisper modeli yuklenemedi", stage="whisper.model", model_path=model_path)
            raise RuntimeError(f"Whisper modeli yuklenemedi: {exc}") from exc

        try:
            use_cuda = torch.cuda.is_available()
            if use_cuda:
                model = model.to("cuda")
            result = model.transcribe(audio_path, language=lang, fp16=use_cuda)
            text = " ".join(
                segment["text"].strip()
                for segment in result.get("segments", [])
                if segment.get("text", "").strip()
            ).strip()
            log_info(logger, "Whisper transkripsiyonu bitti", stage="whisper.transcribe", audio_path=audio_path, text_length=len(text))
            return text
        except Exception as exc:
            log_exception(logger, "Whisper transkripsiyonu hata verdi", stage="whisper.transcribe", audio_path=audio_path)
            raise RuntimeError(f"Whisper transkripsiyonu hata verdi: {exc}") from exc
