import os
import json
from datetime import datetime

from tinydb import TinyDB

TRANSCRIPT_DIR = "transcripts"
DOWNLOAD_DB_PATH = os.path.join(TRANSCRIPT_DIR, "download_history.json")
os.makedirs(TRANSCRIPT_DIR, exist_ok=True)

download_db = TinyDB(DOWNLOAD_DB_PATH)

def get_transcript_filepath(video_id):
    return os.path.join(TRANSCRIPT_DIR, f"{video_id}.json")


def save_transcript_to_file(video_id, data):
    path = get_transcript_filepath(video_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_download_record(video_name, transcript, **extra_fields):
    record = {
        "video_name": video_name,
        "transcript": transcript,
        "created_at": datetime.now().isoformat(),
    }
    record.update({key: value for key, value in extra_fields.items() if value is not None})
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
