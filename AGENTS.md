# Vidigo geliştirme kuralları

## Instagram indirme ve transkript

- Instagram post, reel, profil reels ve ses indirme akışlarında yalnızca `instaloader` kullanılır.
- Reel metadata'si standart `instaloader.Post.from_shortcode()` GraphQL akışıyla alınır. iPhone API veya başka bir Instaloader erişim yolu eklenmez.
- Cookie gerekirse yalnızca `~/cookie/instagram.txt` çözülür ve Instaloader oturumuna yüklenir.
- Akış değişmez: `Instaloader → MP4 → ffmpeg ile M4A → Whisper → transcript`.
- `yt-dlp`, Selenium, `undetected-chromedriver`, tarayıcı otomasyonu veya başka bir Instagram indirme kütüphanesi eklenmez ya da kullanılmaz.
- Birincil akış başarısız olduğunda farklı bir kütüphaneye, servise veya indirme yöntemine fallback uygulanmaz. Hata kullanıcıya açıkça döndürülür.
- Instagram için `transcript_only` isteğinde M4A dosyası `C:\Users\<kullanıcı>\vidigo\<hesap>\ses\` altında tutulur; önceki TinyDB kaydı bu isteği atlatmaz.

## YouTube indirme ve transkript

- YouTube video, playlist ve kanal indirme akışlarında `yt-dlp` kullanılır; Instagram için asla kullanılmaz.
- Cookie gerekirse yalnızca `~/cookie/youtube.txt` kullanılır.
- `transcript_only` modunda önce `yt-dlp` ile mevcut altyazı indirilir ve metne dönüştürülür.
- Altyazı yoksa tek video transkript isteği M4A indirip Whisper ile metin çıkarır.
- Playlist ve kanal URL'leri video listesine genişletilerek her video ayrı işlenir.

## Ortak ses ve kayıt kuralları

- Whisper varsayılan dili Türkçe, varsayılan modeli `medium`dür; M4A doğrudan Whisper'a verilir, WAV ara dosyası oluşturulmaz.
- İndirilen medya kökü `C:\Users\<kullanıcı>\vidigo` olmalıdır; proje köküne veya geçici klasöre medya bırakılmaz.
- Transkript, manifest ve TinyDB kaydı ancak işlem sonucunu doğru yansıtacak şekilde yazılır. Başarısız işlem başarıyla indirilmiş gibi işaretlenmez.
