# API Dokümantasyon Arşivi

> **Kapsam:** Türkiye pazaryerleri ve e-ticaret altyapıları, Amazon SP-API, Meta ekosistemi ile bağımsız kargo firmaları.
>
> **Amaç:** Entegrasyonların kimlik doğrulama, API biçimi, olay alma ve resmi kaynaklarını Everup geliştirmesi için tek yerde tutmak.

## Kısa karar

Adaptörler yalnızca handler içinde API isteği yazılarak canlı çalışmaz. Merkezi action altyapısının çağrıyı doğru sağlayıcı istemcisine taşıyan bir **transport/executor bağlantısına** ihtiyacı vardır. Ortak katman; credential saklama, token yenileme, retry, idempotency, outbox ve görünür hata kaydını sağlamalıdır.

Standart HTTP/webhook sağlayıcıları önce canlılaştırılmalıdır. Amazon'un gerçek zamanlı bildirimleri için buna ek olarak AWS SQS/EventBridge consumer gerekir. Kargo firmaları, pazaryeri/adaptör katmanından bağımsız taşıyıcı adaptörleri olarak tasarlanmalıdır.

## Entegrasyon karşılaştırması

| Tarandı | Platform | Giriş yöntemi | API biçimi | Webhook çeşidi | Kargo rolü | Resmi API dokümanı | Temel yetenekler | İlk geliştirmedeki özel ihtiyaç |
|---|---|---|---|---|---|---|---|---|
| ✅ | **Hepsiburada** | OAuth 2.0 Client Credentials (`client_id` + `client_secret`); bazı eski servislerde HTTP Basic Auth | REST / JSON | Sipariş odaklı HTTP webhook; endpoint Basic Auth ile korunabilir | Taşıyıcı değildir; pazaryeri akışındaki kargo firması, paket, etiket ve takip verisini yönetir | [Geliştirici portalı](https://developers.hepsiburada.com/) · [Sipariş webhook modeli](https://developers.hepsiburada.com/tr/companies/hepsiburada?guide=siparis-webhook-modeli&product=siparis-olusturma-entegrasyonu&view=guide) | Ürün, stok, sipariş, kargo, iade, fatura | Token yönetimi, webhook doğrulama, merkezi transport |
| ✅ | **Trendyol** | HTTP Basic Auth (`sellerId`, API Key, API Secret); `User-Agent` zorunlu | REST / JSON | Olay abonelikli HTTP webhook; teslimatlar için periyodik mutabakat gerekir | Taşıyıcı değildir; anlaşmalı kargo akışındaki paket, etiket, takip ve teslim durumlarını yönetir | [API dokümantasyonu](https://developers.trendyol.com/) · [Webhook modeli](https://developers.trendyol.com/v3.0/docs/1-webhook-model) | Ürün V2, stok/fiyat, sipariş, kargo, iade, fatura | Basic Auth istemcisi, webhook doğrulama, rate-limit uyumu, merkezi transport |
| ⬜ | **Ticimax** | Mağazaya tanımlı Web Servis API kullanıcı bilgileri | SOAP web servisleri | Kamuya açık webhook sözleşmesi bulunmadı; sipariş ve durumlar API sorgusuyla mutabakatlanmalı | Taşıyıcı değildir; mağazadaki kargo firması tanımı üzerinden kargo, takip ve durum bilgisini yönetir | [Web Servis API](https://www.ticimax.com/web-servis-api/) · [Servis dokümantasyonu](https://static.ticimax.com/dokumanlar/webservis.pdf) | Ürün, stok, sipariş, müşteri, kargo ve fatura | SOAP istemcisi, kimlik bilgisi yönetimi, kargo firması eşleme ve merkezi transport |
| ✅ | **IdeaSoft** | API token; mağaza yetkileriyle oluşturulur | REST / JSON | [Webhooks](https://apidoc.ideasoft.dev/docs/webhooks/5cc9374300b99-webhooks); eksik olaylar için API mutabakatı | Taşıyıcı değildir; kargo firması/entegratörü bağlantısıyla etiket, takip numarası ve durum verisini yönetir | [Güncel API dokümantasyonu](https://apidoc.ideasoft.dev/) | Ürün, stok, sipariş, müşteri, kargo ve fatura | **Admin API** kullanılacak; token/izin kapsamları, webhook doğrulama ve merkezi transport |
| ⬜ | **ikas** | Public app: OAuth 2.0 Authorization Code; private app: OAuth 2.0 Client Credentials | GraphQL | Uygulama tarafından kaydedilen, scope tabanlı ve imzalı HTTP webhook | Taşıyıcı değildir; kargo entegrasyonları üzerinden gönderi, takip ve fulfillment bilgisini yönetir | [Geliştirici dokümanları](https://builders.ikas.com/docs) · [Webhook API](https://builders.ikas.com/docs/admin-api/admin-apis/webhook/save-webhook) | Ürün, envanter, sipariş, müşteri, ödeme ve fulfillment | OAuth/token yenileme, webhook imza kontrolü, GraphQL istemcisi, merkezi transport |
| ⬜ | **Shopify** | OAuth access token; özel uygulamada Admin API access token | Admin GraphQL API; REST Admin API legacy | HTTPS webhook; HMAC-SHA256 imzalı teslimat | Taşıyıcı değildir; fulfillment, gönderi, takip numarası ve kargo ücretini yönetir; taşıyıcı/etiket için ek entegrasyon gerekir | [Admin GraphQL API](https://shopify.dev/docs/api/admin-graphql/latest) · [Webhook rehberi](https://shopify.dev/docs/apps/build/webhooks/subscribe) | Ürün, envanter, sipariş, fulfillment, müşteri | Admin GraphQL istemcisi, webhook HMAC doğrulama, merkezi transport |
| ⬜ | **Amazon SP-API** | LWA OAuth token + AWS SigV4 imzası; seller yetkilendirmesi | REST / JSON | Notifications API üzerinden AWS SQS veya EventBridge bildirimi | FBA, Buy Shipping ve seçili hizmetlerde etiket/fulfillment sürecine katılır; satıcı gönderiminde takip bilgisini yönetir | [SP-API referansı](https://developer-docs.amazon.com/sp-api/lang-US/reference/welcome-to-api-references) · [Notifications API](https://developer-docs.amazon.com/sp-api/docs/notifications-api) | Listing, katalog, sipariş, fulfillment, raporlar, finans | SP-API imzalama istemcisi, token yenileme, AWS kuyruk tüketicisi, merkezi transport |
| ⬜ | **Meta / Instagram** | Meta App OAuth access token; gerekli izinler ve App Review | Graph API (REST / JSON) | HTTP GET challenge + POST olay teslimatı; `X-Hub-Signature-256` ile imzalı | Kargo hizmeti veya teslimat altyapısı sağlamaz; mesajlaşma üzerinden takip bilgisi paylaşılabilir | [Meta Graph API](https://developers.facebook.com/docs/graph-api/overview/) · [Instagram webhook'ları](https://developers.facebook.com/documentation/instagram-platform/webhooks) | Instagram içerik, yorum, mesaj, insight; WhatsApp Cloud API | OAuth/token yenileme, webhook doğrulama, Graph API sürüm yönetimi, merkezi transport |

## IdeaSoft API seçimi

Everup için **Admin API** kullanılmalıdır. Bu API, mağazanın yönetim verilerine erişir: ürün, stok, sipariş, müşteri, kargo/teslimat ve fatura. Everup'ın senkronizasyonu ve operasyon ekranları bu kapsamı gerektirir.

**Store API** müşteri vitrini içindir: ürün listeleme/detay, sepet, müşteri oturumu ve checkout odaklı işlemler. Everup müşteriye dönük bir IdeaSoft vitrini veya checkout oluşturmayacaksa ilk kapsamda gerekmez.

## Kargo hizmetleri

Bu servisler Everup'ta pazaryeri adaptörlerinden bağımsız kargo adaptörleri olarak ele alınmalıdır. Her adaptörün ortak sorumlulukları gönderi oluşturma/iptal, etiket-barkod alma, takip ve iade durumlarını normalize etmektir.

| Tarandı | Kargo firması | Giriş yöntemi | API biçimi | Webhook çeşidi | Resmi API dokümanı | Everup'taki temel kullanım |
|---|---|---|---|---|---|---|
| ✅ | **HepsiJET** | Hepsiburada geliştirici hesabından `client_id` + `client_secret` ile token | REST / JSON | Açık webhook sözleşmesi doğrulanmalı; takip için API sorgusu kullanılabilir | [Hepsiburada geliştirici portalı](https://developers.hepsiburada.com/) | Gönderi oluşturma, etiket/barkod, takip ve teslimat durumları |
| ⬜ | **Trendyol Express** | Trendyol Marketplace satıcı kimlik bilgileri: `sellerId`, API Key, API Secret ve `User-Agent` | Trendyol Marketplace REST / JSON | Trendyol webhook'ları; kargo/takip durumu için paket servisleriyle mutabakat | [Paket entegrasyonu](https://developers.trendyol.com/reference/paket-entegrasyonu) · [Depo bilgisi güncelleme](https://developers.trendyol.com/docs/depo-bilgisi-g%C3%BCncelleme) | Trendyol siparişlerinde paket, barkod, kargo firması ve takip durumu yönetimi |
| ⬜ | **Aras Kargo** | Kurumsal müşteri/entegrasyon bilgileri | SOAP (mevcut müşteri web servisi) | Kamuya açık webhook sözleşmesi bulunmadı; takip sorgusu/polling | [Entegrasyon hizmetleri](https://www.araskargo.com.tr/hizmetlerimiz/kurumsal-hizmetlerimiz/entegrasyon-hizmetlerimiz) · [SOAP servis listesi](https://customerws.araskargo.com.tr/arascargoservice.asmx) | Gönderi/barkod üretimi, iptal, takip ve iade |
| ⬜ | **MNG Kargo** | Developer Portal'da oluşturulan API Key + Secret; servis yetkisi gerekir | REST / JSON; eski takip servisleri SOAP | Kamuya açık webhook sözleşmesi bulunmadı; gönderi durumu sorgulanır | [MNG API Portalı](https://apizone.mngkargo.com.tr/en/api) | Gönderi oluşturma, etiket/barkod, ücret hesaplama, takip ve iade |
| ⬜ | **Yurtiçi Kargo** | Kurumsal müşteri web-servis kullanıcı adı/şifresi | SOAP / WSDL | Kamuya açık webhook sözleşmesi bulunmadı; takip sorgusu/polling | [Kurumsal Self Servis](https://test-fe-ykss.yurticikargo.com/) | Siparişten gönderi oluşturma, barkod/etiket, kurye çağırma ve takip |
| ⬜ | **Sürat Kargo** | Sözleşmeli müşteri API bilgileri; firmadan alınmalı | Sağlayıcı sözleşmesinden doğrulanmalı | Sağlayıcıyla doğrulanmalı; başlangıçta takip sorgusu/polling varsayılmalı | [Resmi site](https://www.suratkargo.com.tr/) | Gönderi, etiket/barkod, takip ve iade |
| ⬜ | **PTT Kargo** | Kurumsal entegrasyon bilgileri; firmadan alınmalı | Sağlayıcı sözleşmesinden doğrulanmalı | Sağlayıcıyla doğrulanmalı; başlangıçta takip sorgusu/polling varsayılmalı | [PTT](https://www.ptt.gov.tr/) | Gönderi, barkod, takip ve iade |
| ⬜ | **Kolay Gelsin** | Sözleşmeli müşteri API bilgileri; firmadan alınmalı | Sağlayıcı sözleşmesinden doğrulanmalı | Sağlayıcıyla doğrulanmalı; başlangıçta takip sorgusu/polling varsayılmalı | [Resmi site](https://www.kolaygelsin.com/) | Gönderi, etiket/barkod, takip ve teslimat olayları |

> Webhook dokümanı herkese açık olmayan taşıyıcılarda ilk sürüm için polling tasarlanmalı; kurumsal entegrasyon sözleşmesi alındıktan sonra destek varsa webhook eklenmelidir.

## Olay alma modeli

| Platform | Birincil model | Yedek / mutabakat | Not |
|---|---|---|---|
| Hepsiburada | Webhook | API sorgusu | Sipariş akışı webhook odaklıdır. |
| Trendyol | Webhook | API sorgusu | Kaçan teslimatlar için periyodik kontrol gerekir. |
| Ticimax | API sorgusu | Periyodik mutabakat | Kamuya açık webhook sözleşmesi doğrulanmalıdır. |
| IdeaSoft | Webhook | Admin API sorgusu | Everup için Admin API kullanılır. |
| ikas | Webhook | Admin GraphQL sorgusu | İmza kontrolü yapılmalıdır. |
| Shopify | Webhook | Admin GraphQL sorgusu | Webhook HMAC imzası doğrulanmalıdır. |
| Amazon SP-API | AWS SQS/EventBridge bildirimi | SP-API sorgusu/raporları | AWS consumer gerektirir. |
| Meta | Webhook | Graph API sorgusu | Challenge doğrulaması ve imza kontrolü gerekir. |

## İlk canlı doğrulama kontrol listesi

- [ ] Credential alanları adaptör bazında tanımlı.
- [ ] Merkezi transport canlı API istemcisine bağlanıyor.
- [ ] Tek bir okuma endpoint'i ile bağlantı doğrulanıyor.
- [ ] Tek bir yazma işlemi sandbox/test mağazasında doğrulanıyor.
- [ ] Webhook imzası/challenge doğrulanıyor.
- [ ] Aynı olay iki kez geldiğinde çift kayıt veya çift işlem oluşmuyor.
- [ ] Başarısız çağrı retry ve görünür hata kaydı üretiyor.
- [ ] Periyodik mutabakat işi gereken sağlayıcılarda çalışıyor.
- [ ] Amazon için SQS/EventBridge consumer, gerçek zamanlı bildirim kullanılacaksa çalışıyor.
