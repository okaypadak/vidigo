"""Yerel BgUtil POT sağlayıcısının yaşam döngüsü."""

import atexit
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from utils.runtime_environment import is_container

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 4416
_STARTUP_TIMEOUT_SECONDS = 10
_provider_process: subprocess.Popen | None = None
_provider_lock = threading.Lock()


def _provider_base_url() -> str:
    configured_url = os.environ.get("TEXTFORGE_BGUTIL_BASE_URL", "").strip().rstrip("/")
    if configured_url:
        parsed_url = urlparse(configured_url)
        if parsed_url.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Gomulu BgUtil saglayicisi yalniz loopback adresinde calisabilir.")
        return configured_url

    host = os.environ.get("TEXTFORGE_BGUTIL_HOST", _DEFAULT_HOST).strip() or _DEFAULT_HOST
    port = int(os.environ.get("TEXTFORGE_BGUTIL_PORT", str(_DEFAULT_PORT)))
    return f"http://{host}:{port}"


def _provider_server_home() -> Path:
    configured_home = os.environ.get("TEXTFORGE_BGUTIL_SERVER_HOME", "").strip()
    if configured_home:
        return Path(configured_home)
    return Path(__file__).resolve().parents[1] / "vendor" / "bgutil-provider"


def _is_available(base_url: str) -> bool:
    try:
        with urlopen(f"{base_url}/ping", timeout=0.25) as response:
            return 200 <= response.status < 300
    except (OSError, URLError):
        return False


def _stop_provider() -> None:
    global _provider_process

    process = _provider_process
    _provider_process = None
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def start_bgutil_provider() -> bool:
    """Gömülü HTTP sağlayıcısını başlatır ve yt-dlp'ye loopback URL'sini verir.

    Sağlayıcı yalnız Docker imajında paketlenir. Yerel Windows uygulaması harici
    Docker imajına ya da yerel bir BgUtil sunucusuna bağlanmaz.
    """

    global _provider_process

    if not is_container():
        logger.info("BgUtil yalniz TextForge konteynerinde calistirilir; Windows yerel calismada atlandi.")
        return False

    base_url = _provider_base_url()
    with _provider_lock:
        if _is_available(base_url):
            os.environ["TEXTFORGE_BGUTIL_BASE_URL"] = base_url
            return True

        server_home = _provider_server_home()
        main_script = server_home / "build" / "main.js"
        node_binary = shutil.which("node")
        if not node_binary or not main_script.is_file():
            raise RuntimeError(
                "Konteynerde gomulu BgUtil saglayicisi eksik "
                f"(node={bool(node_binary)}, server_home={server_home})."
            )

        host = os.environ.get("TEXTFORGE_BGUTIL_HOST", _DEFAULT_HOST).strip() or _DEFAULT_HOST
        port = str(int(os.environ.get("TEXTFORGE_BGUTIL_PORT", str(_DEFAULT_PORT))))
        _provider_process = subprocess.Popen(
            [node_binary, str(main_script), "--host", host, "--port", port],
            cwd=server_home,
        )

        deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if _is_available(base_url):
                os.environ["TEXTFORGE_BGUTIL_BASE_URL"] = base_url
                atexit.register(_stop_provider)
                logger.info("Gomulu BgUtil POT saglayicisi baslatildi: %s", base_url)
                return True
            if _provider_process.poll() is not None:
                break
            time.sleep(0.1)

        exit_code = _provider_process.poll()
        _stop_provider()
        logger.warning("Gomulu BgUtil POT saglayicisi baslatilamadi (cikis kodu: %s).", exit_code)
        return False
