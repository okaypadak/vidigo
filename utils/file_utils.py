import os
import json
import re
import unicodedata
from datetime import datetime

from tinydb import TinyDB

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSCRIPT_DIR = os.path.join(_BASE_DIR, "transcripts")
DOWNLOAD_DB_PATH = os.path.join(TRANSCRIPT_DIR, "download_history.json")
DOWNLOAD_MANIFEST_DIR = os.path.join(_BASE_DIR, "downloads", "manifests")
os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_MANIFEST_DIR, exist_ok=True)

download_db = TinyDB(DOWNLOAD_DB_PATH)

def get_transcript_filepath(video_id):
    return os.path.join(TRANSCRIPT_DIR, f"{video_id}.json")


def save_transcript_to_file(video_id, data):
    path = get_transcript_filepath(video_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_download_record(video_name, transcript=None, **extra_fields):
    record = {
        "video_name": video_name,
        "created_at": datetime.now().isoformat(),
    }
    if transcript is not None:
        record["transcript"] = transcript
    record.update({key: value for key, value in extra_fields.items() if value is not None})
    download_db.insert(record)
    return record


def upsert_download_record(video_name, transcript=None, **extra_fields):
    from tinydb import Query
    fields = {key: value for key, value in extra_fields.items() if value is not None}
    record = {"video_name": video_name}
    if transcript is not None:
        record["transcript"] = transcript
    record.update(fields)

    Q = Query()
    existing = None
    for field, value in [
        ("video_id", fields.get("video_id")),
        ("shortcode", fields.get("shortcode")),
        ("file_path", fields.get("file_path")),
        ("url", fields.get("url")),
    ]:
        if value:
            results = download_db.search(Q[field] == value)
            if results:
                existing = results[0]
                break

    if existing:
        record["updated_at"] = datetime.now().isoformat()
        download_db.update(record, doc_ids=[existing.doc_id])
    else:
        record["created_at"] = datetime.now().isoformat()
        download_db.insert(record)
    return record


def load_download_history(limit=None):
    records = download_db.all()
    records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    if limit is not None:
        return records[:limit]
    return records


def load_transcript_from_file(video_id):
    path = get_transcript_filepath(video_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _slugify(value):
    text = unicodedata.normalize("NFKD", str(value or "")).strip().lower()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-_")
    return text or "unnamed"


def _manifest_prefix(source_type):
    return {
        "playlist": "playlist",
        "profile_reels": "ig",
        "video": "video",
        "reel": "reel",
    }.get(source_type, "source")


def get_manifest_filepath(platform, source_name, source_type):
    platform_dir = os.path.join(DOWNLOAD_MANIFEST_DIR, _slugify(platform))
    os.makedirs(platform_dir, exist_ok=True)
    manifest_name = f"{_manifest_prefix(source_type)}-{_slugify(source_name)}.json"
    return os.path.join(platform_dir, manifest_name)


def _load_manifest(path):
    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def upsert_manifest_item(platform, source_name, source_type, source_url, item, **extra_fields):
    path = get_manifest_filepath(platform, source_name, source_type)
    now = datetime.now().isoformat()
    manifest = _load_manifest(path) or {
        "platform": platform,
        "source_name": source_name,
        "source_type": source_type,
        "source_url": source_url,
        "manifest_path": path,
        "created_at": now,
        "updated_at": now,
        "item_count": 0,
        "items": [],
    }

    manifest.update({key: value for key, value in extra_fields.items() if value is not None})
    manifest["updated_at"] = now

    item_copy = dict(item)
    item_copy["recorded_at"] = now
    item_key = (
        item_copy.get("video_id")
        or item_copy.get("shortcode")
        or item_copy.get("id")
        or item_copy.get("webpage_url")
        or item_copy.get("source_url")
        or item_copy.get("file_path")
    )
    item_copy["item_key"] = item_key

    items = manifest.get("items", [])
    for index, existing in enumerate(items):
        if existing.get("item_key") == item_key and item_key is not None:
            items[index] = item_copy
            break
    else:
        items.append(item_copy)

    manifest["items"] = items
    manifest["item_count"] = len(items)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return path, manifest
