# Quantum Terminal Pro — Phase 4

Phase 3 üzerine eklenen salt-okunur **Exit Intelligence** paketidir.

## Amaç

TP3'e neden az ulaşıldığını ölçmek ve çıkış motorunun kârın ne kadarını
yakaladığını görünür hâle getirmek.

## Eklenenler

- Yeni `/exit_report` sayfası
- Yeni `/api/exit-report/<bot>` API'si
- Exit Report CSV export
- MFE ve MAE dağılımları
- Opportunity Lost (`lost_r`)
- Capture Ratio
- 0–100 Exit Quality Score
- TP1 → TP2 → TP3 dönüşüm hunisi
- Exit reason ve exit subreason karşılaştırmaları
- Exit başına toplam/ortalama kaybedilen R
- Shadow Exit kontrol noktaları
- Ayrıntılı Exit Trade Explorer
- Eski JSONL kayıtlarında eksik `lost_r` ve `capture_ratio` alanlarının
  salt-okunur olarak türetilmesi

## Beklenen trade_analytics.jsonl alanları

Temel alanlar:

```json
{
  "trade_id": "abc",
  "symbol": "BTC/USDT:USDT",
  "exit_reason": "K4_BLEEDING",
  "exit_subreason": "momentum_decay",
  "exit_r": 1.2,
  "mfe_r": 1.8,
  "mae_r": 0.35,
  "lost_r": 0.6,
  "capture_ratio": 0.6667,
  "tp1_hit": true,
  "tp2_hit": false,
  "tp3_hit": false
}
```

`lost_r` veya `capture_ratio` yoksa dashboard bunları bellekte türetir; kaynak
JSONL dosyasına yazmaz.

## Formüller

- `lost_r = max(0, mfe_r - exit_r)`
- `capture_ratio = exit_r / mfe_r` (`mfe_r > 0`)
- `exit_quality_score = %75 capture efficiency + %25 MAE control`

Quality skoru 0–100 aralığında sınırlandırılır. Bu skor optimizasyon tanı
metriğidir; botun giriş confidence skoru değildir.

## Güvenlik

Faz 4 salt-okunurdur. Bota emir göndermez ve analitik dosyalarını değiştirmez.
Trade Manager manuel işlem endpoint'i güncel ürün sürümünde adapter kuyruğuna yazar.

## Devam

Funding Engine v2 ve funding analytics Faz 5 paketinde uygulanmıştır.
