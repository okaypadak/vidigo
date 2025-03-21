import whisper

def transcribe_whisper(audio_path, lang="tr", model_size="small"):
    model = whisper.load_model(model_size)
    result = model.transcribe(audio_path, language=lang)
    return {"text": result["text"]}
