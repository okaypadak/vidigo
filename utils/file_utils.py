import os
import json

TRANSCRIPT_DIR = "transcripts"
os.makedirs(TRANSCRIPT_DIR, exist_ok=True)

def get_transcript_filepath(video_id):
    return os.path.join(TRANSCRIPT_DIR, f"{video_id}.json")


def save_transcript_to_file(video_id, data):
    path = get_transcript_filepath(video_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_transcript_from_file(video_id):
    path = get_transcript_filepath(video_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None
