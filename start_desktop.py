import sys
import requests
from PyQt5.QtWidgets import QApplication, QWidget

from templates.form_ui import Ui_Form


class TranscriberApp(QWidget):
    def __init__(self):
        super().__init__()
        self.ui = Ui_Form()
        self.ui.setupUi(self)

        # Buton tıklama işlemi
        self.ui.transcribeButton.clicked.connect(self.transcribe_video)

    def transcribe_video(self):
        url = self.ui.urlInput.text()
        engine = self.ui.engineSelect.currentText()
        self.ui.resultOutput.setPlainText("İşleniyor...")

        try:
            response = requests.get(
                "http://127.0.0.1:5000/transcribe",
                params={"url": url, "engine": engine}
            )
            data = response.json()

            if "transcript" in data:
                if isinstance(data["transcript"], dict):  # YouTubeTranscript API sonucu
                    text = "\n".join([x["text"] for x in data["transcript"]])
                else:
                    text = data["transcript"]["text"]
                self.ui.resultOutput.setPlainText(text)
            else:
                self.ui.resultOutput.setPlainText("Hata: " + data.get("error", "Bilinmeyen hata"))
        except Exception as e:
            self.ui.resultOutput.setPlainText(f"İstek hatası: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TranscriberApp()
    window.show()
    sys.exit(app.exec_())
