# Quantum Terminal Pro — Phase 6 Final

Phase 1–5 üzerine eklenen final tanılama, veri kalitesi ve üretim hazırlığı
paketidir.

## Eklenenler

- Yeni `/diagnostics` sayfası
- Yeni `/api/diagnostics/<bot>` API'si
- Yeni `/api/health` servis sağlık endpoint'i
- Gelişmiş Coin Analytics
- `bars_held`, UTC saat ve haftanın günü Time Analytics
- BTC Filter Debug ve alan kapsama oranı
- Regime Engine audit
- RANGE / NEUTRAL / CHOP / SHOCK giriş ihlali tespiti
- Trend yönüne ters işlem ihlali tespiti
- Exit Trigger Priority çoklu-trigger görünürlüğü
- Symbol Config geçiş ve uyumsuzluk denetimi
- Zorunlu trade alanları veri kalite matrisi
- State/analytics kaynak dosyaları sağlık ve stale kontrolü
- Otomatik config audit

## Korunan bot kimliği

- Yalnızca `TREND_UP`, `STRONG_BULL`, `TREND_DOWN`, `STRONG_BEAR`
- RANGE ve NEUTRAL yasak
- CHOP ve SHOCK yasak
- TREND_UP / STRONG_BULL içinde SHORT yasak
- TREND_DOWN / STRONG_BEAR içinde LONG yasak
- Aynı sembolde eşzamanlı LONG + SHORT yasak

Dashboard bu kuralları değiştirmez; geçmiş kayıtları denetler ve ihlalleri
raporlar.

## Health

`GET /api/health` aşağıdakileri döndürür:

- Config durumu
- Bağlı kaynak sayısı
- Rejim ihlalleri
- Counter-trend ihlalleri
- Salt-okunur durumu

Dosya sağlık ekranı tam sunucu yollarını istemciye göstermez.

## Güvenlik

- Manuel action endpoint'i güncel ürün sürümünde adapter kuyruğuna yazar.
- Faz 6 emir üretmez, göndermez veya pozisyon değiştirmez.
- Dashboard analitik ve state dosyalarına yazmaz.
- İnternete açık kurulumda nginx + HTTPS + authentication kullanılmalıdır.

## Tamamlanma

Bu paket altı fazın birleşik final sürümüdür. Önceki fazların test dosyaları ve
README belgeleri pakette korunmuştur.
