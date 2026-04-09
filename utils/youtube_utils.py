from urllib.parse import urlparse, parse_qs


def extract_youtube_video_id(url):
    if not url:
        return None

    if "://" not in url:
        url = "https://" + url

    parsed = urlparse(url)
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
