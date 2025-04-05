import warnings
import torch
import whisper


def transcribe_whisper(audio_path, lang="tr", model_path="medium"):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        try:
            model = whisper.load_model(model_path)
        except Exception as e:
            print(f"Model yüklenemedi: {e}")
            return "Model yüklenemedi"

        try:
            if torch.cuda.is_available():
                model = model.to("cuda")
                result = model.transcribe(audio_path, language=lang, fp16=True)
            else:
                result = model.transcribe(audio_path, language=lang, fp16=False)

            return result["text"]
        except Exception as e:
            print(f"Transkripsiyon hatası: {e}")
            return "Transkripsiyon hatası"
