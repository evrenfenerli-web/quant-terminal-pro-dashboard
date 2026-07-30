# Funding Engine v2 — Bot Entegrasyonu

`funding_engine.py` dosyasını bot klasörüne kopyalayın.

```python
from funding_engine import get_funding_analytics

current_rate, next_funding_ts = get_cached_funding_rate(symbol)
history = load_symbol_funding_history(symbol)  # oldest -> newest

funding = get_funding_analytics(
    symbol=symbol,
    current_funding=current_rate,
    funding_history=history,
    side=signal,
    config={
        "windows": [90, 30, 8],
        "elevated_z": 1.5,
        "extreme_z": 2.5,
    },
)
```

Sonucu `funding_analytics.jsonl` dosyasına mevcut güvenli JSONL writer ile
ekleyin:

```python
{
    "ts": time.time(),
    "symbol": symbol,
    "funding_rate": current_rate,
    "next_funding_ts": next_funding_ts,
    **funding,
}
```

Önemli:

1. `get_cached_funding_rate()` değiştirilmez.
2. `calculate_funding_cost()` değiştirilmez.
3. K7 funding reversal değiştirilmez.
4. İlk aşamada sonuç yalnızca Telegram ve analytics kaydına eklenir.
5. Funding, trend yönü kurallarını geçersiz kılamaz.
