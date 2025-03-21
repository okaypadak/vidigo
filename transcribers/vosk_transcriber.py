import json
import os
import wave

from vosk import Model as VoskModel, KaldiRecognizer

def transcribe_vosk(audio_path):
    model_path = "models/vosk-tr"
    if not os.path.exists(model_path):
        return {"error": "Vosk Türkçe modeli bulunamadı."}
    model = VoskModel(model_path)
    wf = wave.open(audio_path, "rb")
    rec = KaldiRecognizer(model, wf.getframerate())
    results = []

    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            res = json.loads(rec.Result())
            results.append(res.get("text", ""))
    res = json.loads(rec.FinalResult())
    results.append(res.get("text", ""))
    return {"text": " ".join(results)}