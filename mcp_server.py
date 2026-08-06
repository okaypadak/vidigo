"""Vidigo MCP Server — YouTube linkini alır, Whisper ile transkribe eder, Markdown döndürür."""

import os
import sys
import argparse
import contextlib
import logging

# Proje kökünü path'e ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from utils.video_downloader import (
    download_audio_generic,
    download_youtube_transcript_ytdlp,
    extract_instagram_shortcode,
    is_instagram_url,
    resolve_cookie_file,
)
from utils.youtube_utils import extract_youtube_video_id
<<<<<<< HEAD
from utils.markitdown_converter import convert_file_to_markdown, save_markdown_output, is_audio_or_video_file
=======
>>>>>>> dd2d0e797d099be0142771dcb372e36d62398a1a
from transcribers.whisper_transcriber import transcribe_whisper

mcp = FastMCP("vidigo")

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads", "mcp_temp")
TRANSCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts", "mcp")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(TRANSCRIPT_DIR, exist_ok=True)


@mcp.tool()
def transcribe_youtube(url: str, language: str = "tr", model: str = "medium") -> str:
    """YouTube videosunu indirir, Whisper ile transkribe eder ve Markdown formatında döndürür.

    Args:
        url: YouTube video URL'si (örn. https://www.youtube.com/watch?v=...)
        language: Transkripsiyon dili kodu (örn. 'tr', 'en', 'de'). Varsayılan: 'tr'
        model: Whisper model boyutu ('tiny', 'base', 'small', 'medium', 'large'). Varsayılan: 'medium'

    Returns:
        Transkriptin Markdown formatındaki içeriği
    """
    with _suppress_logs():
        transcript, _ = _transcribe_media_to_markdown(url, language=language, model=model, allowed_platforms={"youtube"})
    return transcript


@mcp.tool()
def transcribe_instagram(url: str, language: str = "tr", model: str = "medium") -> str:
    """Instagram videosunu/Reel'ini indirir, Whisper ile transkribe eder ve Markdown döndürür."""
    with _suppress_logs():
        transcript, _ = _transcribe_media_to_markdown(url, language=language, model=model, allowed_platforms={"instagram"})
    return transcript


@mcp.tool()
def transcribe_url(url: str, language: str = "tr", model: str = "medium") -> str:
    """YouTube veya Instagram URL'sini indirir, Whisper ile transkribe eder ve Markdown döndürür."""
    with _suppress_logs():
        transcript, _ = _transcribe_media_to_markdown(url, language=language, model=model, allowed_platforms={"youtube", "instagram"})
    return transcript


<<<<<<< HEAD
@mcp.tool()
def convert_document(file_path: str) -> str:
    """PDF, Word, Excel veya PowerPoint dosyasını Markdown'a çevirir.

    Args:
        file_path: Dönüştürülecek dosyanın tam yolu (.pdf, .docx, .xlsx, .pptx vb.)

    Returns:
        Dosyanın Markdown formatındaki içeriği
    """
    if not file_path or not file_path.strip():
        raise ValueError("Dosya yolu boş olamaz.")

    abs_path = os.path.abspath(file_path.strip())
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Dosya bulunamadı: {abs_path}")

    if is_audio_or_video_file(abs_path):
        raise ValueError("Ses/video dosyaları için transcribe_youtube aracını kullanın.")

    with _suppress_logs():
        markdown = convert_file_to_markdown(abs_path)
        save_markdown_output(abs_path, markdown, output_dir=TRANSCRIPT_DIR)
    return markdown


=======
>>>>>>> dd2d0e797d099be0142771dcb372e36d62398a1a
def _write_unique(path: str, content: str) -> str:
    if os.path.exists(path):
        base, ext = os.path.splitext(path)
        counter = 2
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        path = f"{base}_{counter}{ext}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip())
        f.write("\n")
    return path


@contextlib.contextmanager
def _suppress_logs():
    previous_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous_level)


def _media_platform_and_stem(url: str) -> tuple[str, str]:
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube", extract_youtube_video_id(url) or "youtube"
    if is_instagram_url(url):
        return "instagram", extract_instagram_shortcode(url) or "instagram"
    raise ValueError("Sadece YouTube ve Instagram URL'leri desteklenmektedir.")


def _transcribe_media_to_markdown(
    url: str,
    language: str = "tr",
    model: str = "medium",
    allowed_platforms: set[str] | None = None,
) -> tuple[str, str]:
    if not url or not url.strip():
        raise ValueError("URL boş olamaz.")

    url = url.strip()
    platform, stem = _media_platform_and_stem(url)
    if allowed_platforms and platform not in allowed_platforms:
        supported = ", ".join(sorted(allowed_platforms))
        raise ValueError(f"Bu komut sadece {supported} URL'leri destekler.")

    if platform == "youtube":
        try:
            cookie_path = resolve_cookie_file("youtube")
            items = download_youtube_transcript_ytdlp(url, save_path=TRANSCRIPT_DIR, cookie_path=cookie_path)
            for item in items:
                transcript = (item.get("transcript") or "").strip()
                if transcript:
                    md_path = _write_unique(os.path.join(TRANSCRIPT_DIR, f"{stem}.md"), transcript)
                    return transcript, md_path
        except Exception:
            pass

    audio_path = download_audio_generic(url, save_path=DOWNLOAD_DIR)

    try:
        transcript = transcribe_whisper(audio_path, lang=language, model_path=model)
    finally:
        try:
            os.remove(audio_path)
        except OSError:
            pass

    md_path = _write_unique(os.path.join(TRANSCRIPT_DIR, f"{stem}.md"), transcript)
    return transcript, md_path


def _run_cli() -> int:
    parser = argparse.ArgumentParser(description="Vidigo MCP server ve CLI araclari.")
    subparsers = parser.add_subparsers(dest="command")

<<<<<<< HEAD
    convert_parser = subparsers.add_parser(
        "convert-document",
        aliases=["convert_document"],
        help="PDF, Word, Excel veya PowerPoint dosyasini Markdown'a cevirir.",
    )
    convert_parser.add_argument("file_path", help="Donusturulecek dosyanin yolu.")

=======
>>>>>>> dd2d0e797d099be0142771dcb372e36d62398a1a
    transcribe_parser = subparsers.add_parser(
        "transcribe-youtube",
        aliases=["transcribe_youtube"],
        help="YouTube videosunu indirip Whisper ile Markdown transkripte cevirir.",
    )
    transcribe_parser.add_argument("url", help="YouTube video URL'si.")
    transcribe_parser.add_argument("--language", "-l", default="tr", help="Dil kodu. Varsayilan: tr")
    transcribe_parser.add_argument("--model", "-m", default="medium", help="Whisper modeli. Varsayilan: medium")

    instagram_parser = subparsers.add_parser(
        "transcribe-instagram",
        aliases=["transcribe_instagram"],
        help="Instagram videosunu indirip Whisper ile Markdown transkripte cevirir.",
    )
    instagram_parser.add_argument("url", help="Instagram video/Reel URL'si.")
    instagram_parser.add_argument("--language", "-l", default="tr", help="Dil kodu. Varsayilan: tr")
    instagram_parser.add_argument("--model", "-m", default="medium", help="Whisper modeli. Varsayilan: medium")

    url_parser = subparsers.add_parser(
        "transcribe-url",
        aliases=["transcribe_url"],
        help="YouTube veya Instagram URL'sini indirip Whisper ile Markdown transkripte cevirir.",
    )
    url_parser.add_argument("url", help="YouTube veya Instagram URL'si.")
    url_parser.add_argument("--language", "-l", default="tr", help="Dil kodu. Varsayilan: tr")
    url_parser.add_argument("--model", "-m", default="medium", help="Whisper modeli. Varsayilan: medium")

    args = parser.parse_args()
<<<<<<< HEAD
    if args.command in {"convert-document", "convert_document"}:
        file_path = os.path.abspath(args.file_path.strip())
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Dosya bulunamadı: {file_path}")
        if is_audio_or_video_file(file_path):
            raise ValueError("Ses/video dosyaları için transcribe_url aracını kullanın.")

        with _suppress_logs():
            markdown = convert_file_to_markdown(file_path)
            output_path = save_markdown_output(file_path, markdown, output_dir=TRANSCRIPT_DIR)
        print(f"[OK] Markdown olusturuldu: {output_path}")
        print(f"[OK] Karakter sayisi: {len(markdown)}")
        return 0

=======
>>>>>>> dd2d0e797d099be0142771dcb372e36d62398a1a
    if args.command in {"transcribe-youtube", "transcribe_youtube"}:
        with _suppress_logs():
            transcript, output_path = _transcribe_media_to_markdown(
                args.url,
                language=args.language,
                model=args.model,
                allowed_platforms={"youtube"},
            )
        print(f"[OK] Markdown olusturuldu: {output_path}")
        print(f"[OK] Karakter sayisi: {len(transcript)}")
        return 0

    if args.command in {"transcribe-instagram", "transcribe_instagram"}:
        with _suppress_logs():
            transcript, output_path = _transcribe_media_to_markdown(
                args.url,
                language=args.language,
                model=args.model,
                allowed_platforms={"instagram"},
            )
        print(f"[OK] Markdown olusturuldu: {output_path}")
        print(f"[OK] Karakter sayisi: {len(transcript)}")
        return 0

    if args.command in {"transcribe-url", "transcribe_url"}:
        with _suppress_logs():
            transcript, output_path = _transcribe_media_to_markdown(
                args.url,
                language=args.language,
                model=args.model,
                allowed_platforms={"youtube", "instagram"},
            )
        print(f"[OK] Markdown olusturuldu: {output_path}")
        print(f"[OK] Karakter sayisi: {len(transcript)}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(_run_cli())
    mcp.run(transport="stdio")
