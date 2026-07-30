# Quantum Terminal Pro — Phase 2A

Phase 1 üzerindeki salt-okunur Trade Manager paketidir.

## Eklenen özellikler

- `/manager` Trade Manager sayfası
- Ayrıntılı açık pozisyon kartları
- Canlı PnL, risk, boyut, kaldıraç, entry/SL/TP, rejim ve confidence
- Open/Pending Orders tablosu
- Trade Event Timeline
- Explain Trade penceresi
- Entry factor score göstergeleri
- Exit Engine K1–K9 canlı göstergeleri
- Current Risk / Current Thesis alanı
- Manuel Close / Partial Close / Move SL / Move TP / BE / Emergency Close butonları
- Güvenlik nedeniyle bütün işlem butonları Phase 2A'da devre dışıdır
- `/api/manager/<market>` salt-okunur API
- `/api/manager/<market>/action` artık config izin veriyorsa manual action kuyruğuna yazar

## Yeni isteğe bağlı state dosyaları

`dashboard_config.json`:

- `orders_state_file`
- `decision_state_file`
- `trade_events_file`

Dosyalar mevcut değilse dashboard hata vermez; ilgili alanlarda “not connected” gösterir.

### decision_state.json örnek yapısı

```json
{
  "BTC/USDT:USDT": {
    "updated_at": 1785360000,
    "risk_level": "MEDIUM",
    "current_thesis": "Trend intact, momentum softening.",
    "summary": "LONG opened after BOS and liquidity sweep.",
    "entry_factors": {
      "BOS": {"score": 10, "max": 10, "detail": "confirmed"},
      "Liquidity": {"score": 8, "max": 10},
      "Volume": {"score": 5, "max": 10}
    },
    "exit_layers": {
      "K1": {"score": 1, "max": 10, "active": false},
      "K4": {"score": 7, "max": 10, "active": false}
    },
    "risk": {
      "level": "MEDIUM",
      "notes": ["BTC momentum weakening"]
    }
  }
}
```

### trade_events.jsonl örnek satır

```json
{"ts":1785360000,"symbol":"BTC/USDT:USDT","event":"ENTRY","detail":"LONG TREND_UP"}
```

## Güvenlik

Güncel ürün sürümünde dashboard emir göndermez; manual action endpoint'i komutu
`manual_actions.jsonl` kuyruğuna yazar. Nihai doğrulama ve emir gönderimi bot
adapter'ının sorumluluğundadır.
Gerçek manuel emirler, doğrulama ve ikinci onay sistemi Phase 2B/3'te eklenecektir.
