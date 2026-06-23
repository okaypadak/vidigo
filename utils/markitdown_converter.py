import os
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKDOWN_OUTPUT_DIR = os.path.join(BASE_DIR, "transcripts", "markitdown")

AUDIO_VIDEO_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".avi",
    ".flac",
    ".flv",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
    ".wmv",
}


class MarkitdownUnavailableError(RuntimeError):
    pass


def is_audio_or_video_file(file_path):
    extension = os.path.splitext(file_path or "")[1].lower()
    return extension in AUDIO_VIDEO_EXTENSIONS


def _load_markitdown():
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise MarkitdownUnavailableError(
            "MarkItDown kurulu degil. requirements.txt yuklendikten sonra tekrar deneyin."
        ) from exc
    return MarkItDown


def convert_file_to_markdown(file_path):
    if not file_path:
        raise ValueError("Dosya yolu gerekli.")

    abs_path = os.path.abspath(file_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError("Markdown'a cevrilecek dosya bulunamadi.")

    if is_audio_or_video_file(abs_path):
        raise ValueError("Ses ve video dosyalari MarkItDown'a gonderilmez; bu dosyalar Whisper akisini kullanmali.")

    MarkItDown = _load_markitdown()
    result = MarkItDown().convert(abs_path)
    markdown = getattr(result, "text_content", None) or getattr(result, "markdown", None) or str(result)
    markdown = (markdown or "").strip()
    if not markdown:
        raise ValueError("MarkItDown bos Markdown ciktisi uretti.")
    return markdown


def _safe_stem(file_path):
    stem = os.path.splitext(os.path.basename(file_path or ""))[0].strip()
    if not stem:
        stem = "document"
    for char in '\\/:*?"<>|':
        stem = stem.replace(char, "_")
    return stem.strip(". ") or "document"


def _unique_markdown_path(output_dir, stem):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{stem}.md")
    if not os.path.exists(path):
        return path

    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = os.path.join(output_dir, f"{stem}-{suffix}.md")
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(output_dir, f"{stem}-{suffix}-{counter}.md")
        counter += 1
    return candidate


def save_markdown_output(source_path, markdown, output_dir=MARKDOWN_OUTPUT_DIR):
    path = _unique_markdown_path(output_dir, _safe_stem(source_path))
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write((markdown or "").strip())
        f.write("\n")
    os.replace(temp_path, path)
    return path
