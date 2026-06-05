import start_web


def test_persist_output_transcript_saves_single_item(monkeypatch):
    calls = []

    def fake_save(video_name, text, folder_name=None, operation_id=None):
        calls.append(
            {
                "video_name": video_name,
                "text": text,
                "folder_name": folder_name,
                "operation_id": operation_id,
            }
        )
        return "transcripts/channel/video.txt"

    monkeypatch.setattr(start_web, "save_output_transcript_to_file", fake_save)

    payload = {
        "source_name": "Channel",
        "items": [
            {
                "title": "Video",
                "transcript": "tek transcript",
            }
        ],
    }

    path = start_web._persist_output_transcript(payload, operation_id="op123")

    assert path == "transcripts/channel/video.txt"
    assert payload["output_transcript_path"] == "transcripts/channel/video.txt"
    assert calls == [
        {
            "video_name": "Video",
            "text": "tek transcript",
            "folder_name": "Channel",
            "operation_id": "op123",
        }
    ]


def test_persist_output_transcript_saves_joined_items(monkeypatch):
    calls = []
    monkeypatch.setattr(
        start_web,
        "save_output_transcript_to_file",
        lambda video_name, text, folder_name=None, operation_id=None: calls.append((video_name, text, folder_name, operation_id)) or "out.txt",
    )

    payload = {
        "source_name": "Playlist",
        "items": [
            {"title": "One", "transcript": "bir"},
            {"title": "Two", "transcript": "iki"},
        ],
    }

    start_web._persist_output_transcript(payload, operation_id="op456")

    assert calls == [("Playlist-output", "bir\n\niki", "Playlist", "op456")]
