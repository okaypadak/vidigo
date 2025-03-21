import os
import wave
from deepspeech import Model as DSModel


def transcribe_deepspeech(audio_path):
    model_path = "models/deepspeech/deepspeech.tflite"
    scorer_path = "models/deepspeech/tr.scorer"
    if not os.path.exists(model_path) or not os.path.exists(scorer_path):
        return {"error": "DeepSpeech modeli veya scorer dosyası eksik."}
    model = DSModel(model_path)
    model.enableExternalScorer(scorer_path)
    with wave.open(audio_path, "rb") as wf:
        audio = wf.readframes(wf.getnframes())
        result = model.stt(audio)
    return {"text": result}