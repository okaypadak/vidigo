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

            # Zaman damgalarını çıkartarak transkripti döndür
            transcribed_text = ""

            # 'segments' içindeki her bir segmenti ele alalım
            for segment in result['segments']:
                start_time = segment['start']  # Segmentin başlangıç zamanı
                end_time = segment['end']  # Segmentin bitiş zamanı
                text = segment['text']  # Segmentin metni

                # Her segmentin zaman damgalarını ve metnini yazdırıyoruz
                transcribed_text += f"Başlangıç: {start_time:.2f}s - Bitiş: {end_time:.2f}s\n"
                transcribed_text += f"Metin: {text}\n\n"

            return transcribed_text
        except Exception as e:
            print(f"Transkripsiyon hatası: {e}")
            return f"Transkripsiyon hatası: {str(e)}"
