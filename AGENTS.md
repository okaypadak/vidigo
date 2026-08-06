# Vidigo geliştirme kuralları

## Instagram indirme

- Instagram post, reel, profil reels ve ses indirme akışlarında yalnızca `instaloader` kullanılır.
- `yt-dlp`, Selenium, `undetected-chromedriver`, tarayıcı otomasyonu veya başka bir Instagram indirme kütüphanesi eklenmez ya da kullanılmaz.
- Birincil akış başarısız olduğunda farklı bir kütüphaneye, servise veya indirme yöntemine fallback uygulanmaz.
- Instaloader içindeki farklı resmi erişim yolları (ör. mevcut oturumun iPhone API istemcisi) kullanılabilir; bu, kütüphane değişimi veya fallback değildir.
- Instagram kaynaklı hatalar görünür ve açıklayıcı biçimde kullanıcıya iletilir; hatayı gizlemek için başka bir indiriciye geçilmez.
