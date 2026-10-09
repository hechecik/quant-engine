"""Veri kaynakları — kripto (Binance halka açık REST) + BIST (Yahoo Finance).

Hiçbir API anahtarı gerekmez. Binance /api/v3/klines herkese açıktır.
"""
from __future__ import annotations

import json
import urllib.request

import pandas as pd

_BINANCE_UC = "https://api.binance.com/api/v3/klines"

# Binance interval kodları (periyot eşlemesi)
_INTERVAL = {
    "1d": "1d", "1h": "1h", "4h": "4h", "15m": "15m", "1w": "1w",
    "1-DAY": "1d", "1-HOUR": "1h", "4-HOUR": "4h", "1-MINUTE": "1m",
}


def kripto_ohlcv(sembol: str = "BTCUSDT", periyot: str = "1d", limit: int = 1000,
                 bitis_ms: int | None = None) -> pd.DataFrame:
    """Binance halka açık klines → (tarih, acilis, max, min, kapanis, hacim). API anahtarı YOK."""
    interval = _INTERVAL.get(periyot, periyot)
    q = f"?symbol={sembol.upper()}&interval={interval}&limit={min(limit, 1000)}"
    if bitis_ms:
        q += f"&endTime={bitis_ms}"
    url = _BINANCE_UC + q
    req = urllib.request.Request(url, headers={"User-Agent": "quant-engine/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        ham = json.loads(r.read().decode())
    if not ham:
        raise RuntimeError(f"Binance veri döndürmedi: {sembol} {interval}")
    df = pd.DataFrame(ham, columns=[
        "acilis_zamani", "acilis", "max", "min", "kapanis", "hacim",
        "kapanis_zamani", "quote_hacim", "islem", "taker_base", "taker_quote", "yoksa0",
    ])
    df = df[["acilis_zamani", "acilis", "max", "min", "kapanis", "hacim"]].copy()
    df["tarih"] = pd.to_datetime(df["acilis_zamani"], unit="ms")
    for c in ("acilis", "max", "min", "kapanis", "hacim"):
        df[c] = df[c].astype(float)
    return df[["tarih", "acilis", "max", "min", "kapanis", "hacim"]]


def bist_ohlcv(sembol: str, baslangic: str = "2023-01-01", bitis: str | None = None,
               periyot: str = "1d") -> pd.DataFrame:
    """BIST hissesi (ör. THYAO) → OHLCV. Yahoo sembolü: THYAO.IS"""
    from .kopru import yfinance_ohlcv

    yf_sembol = sembol.upper() if sembol.upper().endswith(".IS") else f"{sembol.upper()}.IS"
    return yfinance_ohlcv(yf_sembol, baslangic=baslangic, bitis=bitis, periyot=periyot)


def veri_getir(kaynak: str, sembol: str, baslangic: str = "2023-01-01", bitis: str | None = None,
               periyot: str = "1d") -> pd.DataFrame:
    """kaynak='kripto'|'bist' → OHLCV DataFrame."""
    if kaynak == "kripto":
        return kripto_ohlcv(sembol, periyot=periyot)
    if kaynak == "bist":
        return bist_ohlcv(sembol, baslangic=baslangic, bitis=bitis, periyot=periyot)
    raise ValueError(f"Bilinmeyen kaynak: {kaynak} (kripto|bist)")
