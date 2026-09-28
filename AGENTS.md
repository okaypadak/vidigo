# TextForge geliştirme kuralları

## Test çalışma kuralı

- Asla test çalıştırma, test ekleme veya test düzenleme.

## Instagram indirme ve transkript

- Instagram post, reel, profil reels ve ses indirme akışlarında yalnızca `instagrapi` kullanılır.
- Cookie gerekirse yalnızca `~/cookie/instagram.txt` çözülür ve Instagrapi oturumuna yüklenir.
- Akış değişmez: `Instagrapi → MP4 → ffmpeg ile M4A → Whisper → transcript`.
- `instaloader`, `yt-dlp`, Selenium, `undetected-chromedriver`, tarayıcı otomasyonu veya başka bir Instagram indirme kütüphanesi eklenmez ya da kullanılmaz.
- Birincil akış başarısız olduğunda farklı bir kütüphaneye, servise veya indirme yöntemine fallback uygulanmaz. Hata kullanıcıya açıkça döndürülür.
- Instagram için `transcript_only` isteğinde M4A dosyası `C:\Users\<kullanıcı>\textforge\<hesap>\ses\` altında tutulur; önceki TinyDB kaydı bu isteği atlatmaz.

## YouTube indirme ve transkript

- YouTube video, playlist ve kanal indirme akışlarında `yt-dlp` kullanılır; Instagram için asla kullanılmaz.
- Cookie gerekirse yalnızca `~/cookie/youtube.txt` kullanılır.
- `transcript_only` modunda önce `yt-dlp` ile mevcut altyazı indirilir ve metne dönüştürülür.
- Altyazı yoksa tek video transkript isteği M4A indirip Whisper ile metin çıkarır.
- Playlist ve kanal URL'leri video listesine genişletilerek her video ayrı işlenir.

## Ortak ses ve kayıt kuralları

- Whisper varsayılan dili Türkçe, varsayılan modeli `medium`dür; M4A doğrudan Whisper'a verilir, WAV ara dosyası oluşturulmaz.
- İndirilen medya kökü `C:\Users\<kullanıcı>\textforge` olmalıdır; proje köküne veya geçici klasöre medya bırakılmaz.
- Transkript, manifest ve TinyDB kaydı ancak işlem sonucunu doğru yansıtacak şekilde yazılır. Başarısız işlem başarıyla indirilmiş gibi işaretlenmez.

## Windows ve Docker çalışma ortamları

- Yerel Windows başlatıcıları `.venv312\\Scripts\\python.exe` kullanır ve `TEXTFORGE_RUNTIME=windows` ayarlar. Medya kökü `C:\\Users\\<kullanıcı>\\textforge`, cookie kökü `C:\\Users\\<kullanıcı>\\cookie`dir.
- Docker imajı Linux'tur; `TEXTFORGE_RUNTIME=container`, medya kökü `/data/textforge` ve cookie kökü `/data/cookie`dir. `start_docker_gpu.bat`, Windows'taki bu iki klasörü sırasıyla konteynere bağlar; cookie bağlaması salt-okunurdur.
- Windows'ta FFmpeg önce proje içindeki `ffmpeg\\ffmpeg.exe`, ardından `PATH` üzerinde aranır. Konteynerde Debian paketindeki `/usr/bin/ffmpeg` kullanılır; Windows `.exe` dosyası veya proje içi paket Linux'ta seçilmez.
- BgUtil ayrı bir Docker imajı ya da Windows süreci olarak çalıştırılmaz. Yalnız TextForge Docker konteynerinde, `start_web.py` tarafından loopback (`127.0.0.1:4416`) üzerinde başlatılır. Windows'ta BgUtil başlatılmaz ve harici bir sağlayıcıya bağlanılmaz.

## CUDA ve PyTorch

- NVIDIA GPU desteği gereken kurulumlarda önce resmî PyTorch kaynaklarından Windows, Python sürümü ve CUDA için desteklenen en güncel kararlı PyTorch derlemesi doğrulanır.
- Bu doğrulama yapılmadan rastgele veya eski bir CUDA/PyTorch sürümü denenmez; yalnızca doğrulanan sürüm kurulabilir.
- Kurulum ve doğrulama, uygulamanın kullandığı sanal ortamda (`.venv312`) yapılır; sistem genelindeki Python paketleri esas alınmaz.

## Web Markdown adapter'ları

- Kullanıcı bir site için "adapter yap" dediğinde adapter, yalnızca açılış sayfasını kaydetmekle yetinmez; render edilmiş sol menüyü/rehber ağacını bulur, ilgili tüm yaprak sayfaları tek tek gezer ve içeriklerini birlikte toplar. Menü yoksa veya doküman gerçekten tek sayfaysa bu durum açıkça belirtilir.
- `TrendyolDocumentationAdapter` (`trendyol_documentation`)
- `IdeasoftStoplightAdapter` (`ideasoft_stoplight`)
- `MetaInstagramPlatformAdapter` (`meta_instagram_platform`)
- `HepsiburadaPortalAdapter` (`hepsiburada_portal`)
