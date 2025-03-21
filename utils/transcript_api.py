from youtube_transcript_api import TranscriptsDisabled, YouTubeTranscriptApi, NoTranscriptFound


def get_transcript_api(video_id, lang="tr"):
    try:
        transcript_list = YouTubeTranscriptApi.list(video_id)
        if transcript_list.find_manually_created_transcript([lang]):
            return transcript_list.find_manually_created_transcript([lang]).fetch()
        elif transcript_list.find_generated_transcript([lang]):
            return transcript_list.find_generated_transcript([lang]).fetch()
    except (TranscriptsDisabled, NoTranscriptFound):
        return None