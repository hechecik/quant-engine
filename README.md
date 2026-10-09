# quant-engine

**ICT (Inner Circle Trader) stratejisi için NautilusTrader tabanlı backtest + paper yürütme motoru.**

Mantık kaynağı: [ArunKBhaskar/PineScript](https://github.com/ArunKBhaskar/PineScript) (Pine v5 indikatör koleksiyonu, MPL-2.0).
Pine kodu TradingView'a bağımlı olduğu için **doğrudan çalıştırılamaz**; bu repoda o mantık Python'a taşınmış ve gerçek veriyle test edilmiştir.

## Katmanlar

| Katman | Nerede | Ne yapar |
|---|---|---|
| 1. Veri | `bist-panel` (+ bu repo `quantlib/veri.py`) | OHLCV çekimi (Binance / Yahoo Finance) |
| 2. Sinyal | `bist-panel/scripts/ict.py` + `quantlib/ict.py` | ICT indikatör seti → skor (AL/TUT/SAT) |
| 3. Yürütme | **bu repo** | Backtest + paper yürütme (NautilusTrader) |

`quantlib/ict.py` katman 2 ile **aynı** dosyadır — panel ile motor aynı mantığı kullanır, tek doğruluk kaynağı vardır.

## ICT indikatör seti (`quantlib/ict.py`)

- **ZigZag / MSS** — piyasa yapısı kırılımı (Market Structure Shift)
- **Order Block** — son ters mum + displacement onayı, mitigation durumu
- **Mitigation Block** — kırılmış yapının geri test edildiği blok
- **Displacement** — ortalamanın üstünde impulsif hareket (ATR tabanlı)
- **FVG** — Fair Value Gap (dengesizlik boşluğu), doldurulma durumu
- **EQH / EQL** — eşit zirveler / eşit dipler (likidite havuzları)
- **Liquidity Sweep** — likidite süpürme (stop avı)
- **Liquidity Void** — likidite boşluğu (tek taraflı hızlı hareket)
- **Market Profile** — POC / değer alanı (VAH-VAL)

### Skor kuralı (deterministik, kodda açık)

| Koşul | Puan |
|---|---|
| 24s değişim > +%3 / < −%3 | ±1 |
| 7g değişim > +%8 / < −%8 | ±1 |
| Fiyat 7g aralığının üst/alt %25'inde | ±1 |
| Korku & Açgözlülük < 25 / > 75 | ±1 |

`skor ≥ 3 → AL`, `skor ≤ −3 → SAT`, arası `TUT`. Stablecoinlerde skor hesaplanmaz (`PARİTE`).

> Not: panel tarayıcısı ile strateji aynı eşiği (±3) kullanır. Giriş ayrıca **taze MSS** ile tetiklenir.

## Kurulum

NautilusTrader Rust çekirdeği içerir; **Python 3.13–3.14** hedefler.
Bu depo Python **3.12** ile de çalışır (tekerlek mevcut) — üretim için 3.13+ önerilir.

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install nautilus_trader pandas yfinance
```

Doğrulama:

```bash
.venv/bin/python -c "from nautilus_trader.backtest.engine import BacktestEngine; print('ok')"
```

## Kullanım

### Backtest

```bash
# Kripto (Binance halka açık REST, API anahtarı YOK)
.venv/bin/python run_backtest.py --kaynak kripto --sembol BTCUSDT --periyot 1d --bakiye 100000

# BIST (Yahoo Finance .IS)
.venv/bin/python run_backtest.py --kaynak bist --sembol THYAO --baslangic 2023-01-01 --bakiye 1000000

# Kısa (short) açık + daha düşük eşik
.venv/bin/python run_backtest.py --kaynak kripto --sembol BTCUSDT --short --esik 2
```

Rapor `data/*.json` içine yazılır (`--cikti` ile değiştirilebilir).

### Canlı paper yürütme (gerçek veri, paper hesap)

```bash
.venv/bin/python scripts/canli_paper.py --sembol GARAN --periyot-sn 60
```

Gerçek BIST verisi periyodik çekilir ve çalışan motora bar olarak beslenir; emirler paper hesapta dolar.

> Gerçek broker yürütmesi için NautilusTrader `TradingNode` + bir `ExecutionClient` gerekir. Bu repoda yalnızca backtest + paper vardır; hiçbir yerde gerçek emir gönderilmez.

## Doğrulanmış sonuçlar (gerçek veri)

Varsayılan ayarlar: long-only, eşik ±3, stop = 2×ATR, hedef = 3×ATR, tahsis %95.

| Sembol | Kaynak | Dönem | Bar | Getiri | İşlem | İsabet |
|---|---|---|---|---|---|---|
| BTCUSDT | Binance | 2024-01-14 → 2026-10-09 | 1000 | **−30.57%** | 39 | %38.5 |
| THYAO | Yahoo (.IS) | 2023-01-02 → 2026-10-08 | 941 | **+43.90%** | 37 | %48.6 |

**Dürüst değerlendirme:** Strateji BIST hissesinde pozitif, kripto (BTC) long-only günlükte negatiftir.
Bu bir parametre taraması / optimizasyon değildir — kasten optimize edilmemiş, raporlanmış ilk sonuçtur.
Kripto için short ve farklı periyot (4s) denenmelidir; geçmiş performans gelecek performansı garanti etmez.

## Dosya düzeni

```
quant-engine/
├── run_backtest.py            # backtest CLI (kripto + BIST)
├── scripts/canli_paper.py     # canlı paper yürütme CLI
├── strategies/ict_strategy.py # NautilusTrader stratejisi (MSS/skor girişi, ATR stop/hedef)
├── bist/adapter.py            # BIST custom adapter (enstrüman + veri + venue + paper feed)
├── quantlib/
│   ├── ict.py                 # ICT indikatör seti (panel ile aynı dosya)
│   ├── kopru.py               # OHLCV → Instrument/Bar köprüsü
│   └── veri.py                # Binance + Yahoo Finance veri çekimi
├── configs/ict.yaml           # strateji ayar örneği
├── data/                      # backtest raporları (JSON)
└── tests/
```

## Lisans / atıf

- ICT mantığı: ArunKBhaskar/PineScript (MPL-2.0) esinlenmesiyle Python'a çevrilmiştir.
- Motor: [nautilus_trader](https://github.com/nautechsystems/nautilus_trader) (LGPL-3.0).
- Bu repodaki kod yalnızca araştırma/backtest amaçlıdır, yatırım tavsiyesi değildir.
