import sys
import requests
from PyQt5.QtWidgets import QApplication, QWidget

from templates.form_ui import Ui_Form


class TranscriberApp(QWidget):
    def __init__(self):
        super().__init__()
        self.ui = Ui_Form()
        self.ui.setupUi(self)

        self.ui.transcribeButton.clicked.connect(self.transcribe_video)

    def transcribe_video(self):
        url = self.ui.urlInput.text().strip()
        if not url:
            self.ui.resultOutput.setPlainText("Hata: URL gerekli")
            return

        self.ui.resultOutput.setPlainText("Isleniyor...")

        try:
            response = requests.post(
                "http://127.0.0.1:5000/download_media",
                json={"url": url, "mode": "transcript_only"},
            )
            response.raise_for_status()
            data = response.json()

            if data.get("error"):
                self.ui.resultOutput.setPlainText("Hata: " + data.get("error", "Bilinmeyen hata"))
                return

            transcripts = [
                item.get("transcript", "").strip()
                for item in data.get("items", [])
                if item.get("transcript", "").strip()
            ]
            if transcripts:
                text = "\n\n".join(transcripts)
                self.ui.resultOutput.setPlainText(text)
            else:
                self.ui.resultOutput.setPlainText("Hata: Transkript bulunamadi")
        except requests.HTTPError as e:
            try:
                data = e.response.json()
                message = data.get("error", str(e))
            except ValueError:
                message = str(e)
            self.ui.resultOutput.setPlainText(f"Istek hatasi: {message}")
        except Exception as e:
            self.ui.resultOutput.setPlainText(f"Istek hatasi: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TranscriberApp()
    window.show()
    sys.exit(app.exec_())
