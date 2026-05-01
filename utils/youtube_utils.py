from urllib.parse import urlparse, parse_qs


def _parse_url(url):
    if not url:
        return None

    if "://" not in url:
        url = "https://" + url

    return urlparse(url)


def is_youtube_url(url):
    parsed = _parse_url(url)
    if not parsed:
        return False

    host = parsed.netloc.lower()
    return host.endswith("youtu.be") or "youtube.com" in host


def extract_youtube_video_id(url):
    parsed = _parse_url(url)
    if not parsed:
        return None

    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if host.endswith("youtu.be"):
        return path.split("/")[0] if path else None

    if "youtube.com" not in host:
        return None

    if path == "watch":
        return parse_qs(parsed.query).get("v", [None])[0]

    parts = path.split("/")
    if len(parts) >= 2 and parts[0] in ("shorts", "embed", "v"):
        return parts[1]

    return parse_qs(parsed.query).get("v", [None])[0]


def extract_youtube_playlist_id(url):
    parsed = _parse_url(url)
    if not parsed:
        return None

    if not is_youtube_url(url):
        return None

    return parse_qs(parsed.query).get("list", [None])[0]


def is_youtube_playlist_url(url):
    return extract_youtube_playlist_id(url) is not None


def is_youtube_channel_url(url):
    parsed = _parse_url(url)
    if not parsed:
        return False

    if not is_youtube_url(url):
        return False

    path = parsed.path.strip("/")
    if not path:
        return False

    parts = path.split("/")
    if parts[0] in ("channel", "c", "user"):
        return len(parts) >= 2

    return parts[0].startswith("@")


def extract_youtube_channel_name(url):
    if not is_youtube_channel_url(url):
        return None

    parsed = _parse_url(url)
    path = parsed.path.strip("/")
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None

    head = parts[0]
    if head.startswith("@"):
        return head.lstrip("@") or None

    if head in ("channel", "c", "user") and len(parts) >= 2:
        return parts[1]

    return None
