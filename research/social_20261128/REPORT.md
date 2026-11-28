# Sosyal medya analizi — 2026-11-28 (ScrapeCreators)

Kaynak: ScrapeCreators API (9 kredi kullanıldı, 90 kaldı). Instagram reel araması: "cpsc compliance", "amazon children's product certificate", "amazon listing compliance". TikTok araması: "cpsc certificate amazon", "amazon compliance documents". Hesap analizi: @uscpsc ve @noahmincis (son 12 reel, medyan bazlı outlier). 2 transkript.

## 1. Nişte ulaşım nerede?

| Hesap / içerik tipi | Tipik izlenme | Not |
|---|---|---|
| B2B uygunluk anlatıcıları (avukat, danışman, lab) | 70–1.000 | @amazonsellerslawyer, @appealwizards, @coretech.testingc, @flatfee_corp |
| Bizim hesap (@mzconsulting.llc, 9 takipçi) | 10–110 | Aynı bant, sorun format değil kitle |
| @uscpsc (resmi kurum) | medyan ~19.000 | Tüketici güvenliği hikâyeleri |
| Haber kanalları / Consumer Reports | 1.000–107.000 | "Squishy toy" haberleri |

Sonuç: Uygunluk dosyası içeriği nişte kimseye büyük izlenme getirmiyor. Büyük izlenme **somut ürün + test/el koyma görüntüsü + güncel haber** üçlüsünden geliyor.

## 2. Outlier'lar (hesabın kendi medyanına göre)

- @uscpsc — "Watch as CPSC port investigator… tests a shipment of Halloween-themed squishy toys": 36.6k izlenme (1.9x), **70 yorum** (hesabın en çok yorum alanı). Transkript: ürünü kesip test aparatına koyuyor, su boncukları aparattan geçmiyor → "sample and detain", "recommended for seizure". Format: limanda gerçek test, 60 sn, tek ürün.
- @uscpsc — squishy/fidget toy uyarısı 66k (3.5x); Şükran Günü yangını 56k (2.9x): **mevsimsel/güncel** konu.
- @noahmincis (Walmart satıcı koçu) — "Walgreens'ten 29$'a aldım, Walmart'ta sattım" 24.5k (20.4x): **para + hikâye** kancası. Aynı kişinin "Walmart artık 12 yaş altı ürünlerde CPC + test raporu istiyor" PSA'sı sadece 385 izlenme.

## 3. Trend konular (şu an konuşulanlar)

1. **Sahte "squishy" oyuncaklar / su boncukları** — CPSC, Consumer Reports, yerel haberler, Amazon'un ürün kaldırması. Çok yüksek hacim.
2. **CPSC eFiling zorunluluğu (8 Temmuz 2026)** — FedEx, Çinli nakliyeciler (@lilyshipping1, @wingfreight, @yiba1818) anlatıyor: "beyan yoksa mal tutulur". İthalatçı kitlemizin tam konusu.
3. **Walmart'ın çocuk ürünlerinde CPC yükleme şartı** — satıcı koçları konuşuyor, izlenme düşük ama hedef kitle doğru.
4. AB GPSR, Prop 65 (CPSC dışı, bizim kapsamımız değil).

## 4. Rakip CTA'ları
- "Comment HELP if…" (@amazonsellerslawyer) — bizim "Comment M&Z" kurgusunun aynısı; nişte yaygın.
- "Job link in bio", "link in bio" — standart.

## 5. Öneriler (doğruluk kurallarıyla uyumlu)

1. **Perşembe HOLD sorununu çöz**: eFiling (16 CFR 1110) tarihleri eCFR'de doğrulanabiliyorsa perşembe "deadline" konusu bu olsun; ithalatçılar şu an bunu konuşuyor. (Yayından önce eCFR metniyle doğrulanacak; 20 Kasım reeli 1110.13(a)(1) üzerindeydi, açı farklı tutulacak.)
2. **Su boncuğu / squishy** — güncel ve yüksek hacimli. Oyuncak Finder demosu: "Squishy satıyorsan hangi kurallar geçerli?" Sadece eCFR'de doğrulanan şartlar söylenecek (su boncuğu şartı ASTM F963 üzerinden 16 CFR 1250'de mi, önce kontrol).
3. **Görsel format**: En çok yorumu alan içerik "test aparatı + ürün" görüntüsü. Bunu Blender ile 3D olarak üretebiliriz (ürün aparattan geçmiyor animasyonu) — gerçek kurum logosu ve gerçek liman adı olmadan.
4. **Kanca**: para/sonuç ("tutulan konteyner, el konulan mal") rakip koçlarda çalışıyor; bizde zaten "cost" günü var, kancayı ürün + sonuç şeklinde kuralım.
5. **Walmart CPC**: Walmart'ın kendi kuralları eCFR/CPSC/FCC kaynağı olmadığı için iddia olarak kullanamayız; yalnızca "perakendeci sertifika istedi" senaryosu olarak (zaten retailer_meeting dünyası var).

Ham veriler: bu klasördeki *.json dosyaları (repo'ya eklenmedi, sadece bu oturumda).
