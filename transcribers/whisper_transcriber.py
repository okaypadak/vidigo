import warnings
import torch
import whisper

def transcribe_whisper(audio_path, lang="tr", model_path="medium", with_timestamps=False):
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

            transcribed_text = ""

            for segment in result['segments']:
                text = segment['text']
                if with_timestamps:
                    start_time = segment['start']
                    end_time = segment['end']
                    transcribed_text += f"Başlangıç: {start_time:.2f}s - Bitiş: {end_time:.2f}s\n"
                transcribed_text += f"Metin: {text}\n\n" if with_timestamps else f"{text.strip()} "

            return transcribed_text.strip()
        except Exception as e:
            print(f"Transkripsiyon hatası: {e}")
            return f"Transkripsiyon hatası: {str(e)}"
