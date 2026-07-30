# Quantum Terminal Pro — Phase 5

Phase 4 üzerine eklenen salt-okunur **Funding Engine v2 + Funding
Intelligence** paketidir.

## Amaç

Sabit funding eşikleri yerine her sembolün kendi funding dağılımını kullanmak.
BTC funding'i BTC geçmişiyle, SOL funding'i SOL geçmişiyle karşılaştırılır.

## Eklenenler

- Bağımsız `funding_engine.py`
- `get_funding_analytics()` entegrasyon fonksiyonu
- 90 → 30 → 8 baseline pencere seçimi
- `baseline_mean`, `baseline_std`, `z_score`, `normalized`
- `NORMAL`, `ELEVATED`, `EXTREME` funding sınıfları
- `LONGS_PAY`, `SHORTS_PAY`, `BALANCED` crowding yorumu
- LONG/SHORT için adverse/favorable gösterimi
- Yeni `/funding` dashboard'u
- Yeni `/api/funding/<bot>` API'si
- Funding analytics CSV export
- Sembol bazında funding maliyeti
- Eksik baseline sembol uyarıları

Başlangıç baseline sembolleri:

- BTC, ETH, LINK, XRP, SOL, SUI, ADA

## Veri dosyası

`dashboard_config.json` içindeki:

```json
"funding_analytics_file": "/home/ubuntu/okx_bot/funding_analytics.jsonl"
```

Her ölçüm için örnek satır:

```json
{
  "ts": 1785400000,
  "symbol": "BTC/USDT:USDT",
  "funding_rate": 0.0001,
  "next_funding_ts": 1785427200,
  "mark_price": 118000
}
```

Trade bazında maliyet analizi için `trade_analytics.jsonl` kayıtlarına
`funding_cost_usd` alanı eklenebilir.

## Entegrasyon sınırı

Bu faz mevcut aşağıdaki fonksiyonları değiştirmez:

- `get_cached_funding_rate()`
- `calculate_funding_cost()`
- Smart Exit K7

Motor yalnızca mevcut funding rate ve geçmiş seri kendisine verildikten sonra
analitik üretir. Telegram ve `trade_analytics` kayıtlarına eklenebilir.

## Bot kimliği

- RANGE ve NEUTRAL girişleri açılmaz.
- Aynı sembolde eşzamanlı LONG + SHORT açılmaz.
- TREND_UP / STRONG_BULL içinde SHORT açılmaz.
- TREND_DOWN / STRONG_BEAR içinde LONG açılmaz.

Funding normalizasyonu bu trend kurallarını gevşetmez veya tersine çevirmez.

## Güvenlik

Dashboard salt-okunurdur. Funding Engine v2 emir göndermez. Trade Manager
manuel action endpoint'i güncel ürün sürümünde adapter kuyruğuna yazar. Alpaca/US stocks için funding
devre dışıdır.
