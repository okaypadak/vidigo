"""TextForge'un Windows ve konteyner çalışma ortamı ayrımları."""

import os
from pathlib import Path


def is_windows() -> bool:
    """Uygulamanın yerel Windows sürecinde çalışıp çalışmadığını döndürür."""
    return os.name == "nt"


def is_container() -> bool:
    """Uygulamanın bir OCI/Docker konteynerinde çalışıp çalışmadığını döndürür."""
    configured_runtime = os.environ.get("TEXTFORGE_RUNTIME", "").strip().lower()
    if configured_runtime in {"container", "docker"}:
        return True
    if configured_runtime in {"windows", "native"}:
        return False
    if is_windows():
        return False
    return Path("/.dockerenv").exists()


def runtime_name() -> str:
    """Durum ve günlük kayıtları için kanonik çalışma ortamı adı."""
    if is_container():
        return "container"
    if is_windows():
        return "windows"
    return "native"
