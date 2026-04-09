import os
import warnings
import torch
import whisper
from utils.ffmpeg_utils import get_ffmpeg_binary


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


def _format_timestamp(seconds):
    total_ms = max(int(round(float(seconds) * 1000)), 0)
    hours, remainder = divmod(total_ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"
    return f"{minutes:02}:{secs:02}.{millis:03}"


def transcribe_whisper(audio_path, lang="tr", model_path="medium", with_timestamps=False):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        try:
            _ensure_ffmpeg_available()
            model = whisper.load_model(model_path)
        except Exception as e:
            print(f"Model yuklenemedi: {e}")
            return "Model yuklenemedi"

        try:
            if torch.cuda.is_available():
                model = model.to("cuda")
                result = model.transcribe(audio_path, language=lang, fp16=True)
            else:
                result = model.transcribe(audio_path, language=lang, fp16=False)

            transcribed_lines = []

            for segment in result["segments"]:
                text = segment["text"].strip()
                if not text:
                    continue
                if with_timestamps:
                    start_time = segment["start"]
                    end_time = segment["end"]
                    transcribed_lines.append(
                        f"[{_format_timestamp(start_time)} - {_format_timestamp(end_time)}] {text}"
                    )
                else:
                    transcribed_lines.append(text)

            if with_timestamps:
                return "\n".join(transcribed_lines).strip()
            return " ".join(transcribed_lines).strip()
        except Exception as e:
            print(f"Transkripsiyon hatasi: {e}")
            return f"Transkripsiyon hatasi: {str(e)}"
