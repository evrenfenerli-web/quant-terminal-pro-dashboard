# Quantum Terminal Pro — Phase 3

Phase 2'nin üzerine kurulu profesyonel terminal çalışma alanı paketidir.

## Yeni sayfa

`/workspace`

## Eklenen özellikler

- Sabitlenebilir sol menü
- Raptiye açıkken menü sürekli açık
- Raptiye kapalıyken menü dar kalır, üzerine gelince açılır
- Tercih tarayıcı `localStorage` içinde saklanır
- Çoklu workspace
- Workspace oluşturma / değiştirme / kaydetme
- 1 / 2 / 4 / 6 / 8 grafik yerleşimi
- Workspace başına ayrı sembol ve timeframe
- Multi-chart görünümü
- Watchlist Pro
- Watchlist arama ve filtreleme
- Pozisyonu olan semboller filtresi
- Trend ve Strong rejim filtreleri
- Market Regime Map
- Momentum tabanlı görsel Market Heatmap
- Pearson getiri korelasyon matrisi
- Çalışma alanı ayarlarının tarayıcıda saklanması

## Güvenlik

Faz 3 hâlâ salt-okunurdur. Trade Manager üzerindeki emir butonları devre dışıdır.
Heat score yalnızca görselleştirme içindir; botun gerçek giriş confidence skoru değildir.

## Kurulum

Phase 3 ZIP içeriğini mevcut dashboard klasörünün üzerine kopyalayın ve:

```bash
pip install -r requirements.txt
python3 app.py
```

Ardından:

- Overview: `/`
- Workspace: `/workspace`
- Trade Manager: `/manager`
- Analytics: `/analytics`
