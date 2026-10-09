"""OHLCV  →  NautilusTrader Instrument + Bar köprüsü.

Panel tarafındaki sözlük/liste verisini (tarih, acilis, max, min, kapanis, hacim)
NautilusTrader'ın Bar nesnelerine ve enstrüman tanımlarına çevirir.
"""
from __future__ import annotations

import pandas as pd

from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair, Equity
from nautilus_trader.model.objects import Price, Quantity

_AGREGASYON = {
    "MINUTE": BarAggregation.MINUTE,
    "MIN": BarAggregation.MINUTE,
    "HOUR": BarAggregation.HOUR,
    "DAY": BarAggregation.DAY,
    "GUN": BarAggregation.DAY,
}


def bar_tipi(instrument_id: InstrumentId, periyot: str = "1-DAY") -> BarType:
    """'1-DAY', '60-MINUTE', '240-MINUTE' gibi periyottan BarType üretir."""
    adim_str, agg_str = periyot.split("-")
    agg = _AGREGASYON[agg_str.upper()]
    spec = BarSpecification(int(adim_str), agg, PriceType.LAST)
    # Veri dışarıdan (bizim) geldiği için kaynak EXTERNAL olmak zorunda.
    return BarType(instrument_id, spec, AggregationSource.EXTERNAL)


def bist_enstruman(sembol: str, fiyat_hassasiyeti: int = 2, isin: str | None = None) -> Equity:
    """Borsa İstanbul hissesi için NautilusTrader Equity enstrümanı."""
    return Equity(
        instrument_id=InstrumentId.from_str(f"{sembol.upper()}.XIST"),
        raw_symbol=Symbol(sembol.upper()),
        currency=__import__("nautilus_trader.model.currencies", fromlist=["TRY"]).TRY,
        price_precision=fiyat_hassasiyeti,
        price_increment=Price.from_str(str(round(10 ** -fiyat_hassasiyeti, fiyat_hassasiyeti))),
        lot_size=Quantity.from_int(1),
        isin=isin,
        ts_event=0,
        ts_init=0,
    )


def kripto_enstruman(sembol: str, borsa: str = "BINANCE", fiyat_hassasiyeti: int = 2,
                     miktar_hassasiyeti: int = 6) -> CurrencyPair:
    """BTCUSDT gibi bir parite için CurrencyPair enstrümanı (ör. borsa=BINANCE)."""
    from nautilus_trader.model.currencies import Currency

    sembol = sembol.upper()
    for quote in ("USDT", "USDC", "BUSD", "TRY", "USD", "EUR", "BTC", "ETH", "BNB"):
        if sembol.endswith(quote) and len(sembol) > len(quote):
            base, quote_ccy = sembol[: -len(quote)], quote
            break
    else:
        raise ValueError(f"Parite çözümlenemedi: {sembol} (ör. BTCUSDT)")
    return CurrencyPair(
        instrument_id=InstrumentId.from_str(f"{sembol}.{borsa.upper()}"),
        raw_symbol=Symbol(sembol),
        base_currency=Currency.from_str(base),
        quote_currency=Currency.from_str(quote_ccy),
        price_precision=fiyat_hassasiyeti,
        size_precision=miktar_hassasiyeti,
        price_increment=Price.from_str(str(round(10 ** -fiyat_hassasiyeti, fiyat_hassasiyeti))),
        size_increment=Quantity.from_str(str(round(10 ** -miktar_hassasiyeti, miktar_hassasiyeti))),
        ts_event=0,
        ts_init=0,
    )


def barlar(df: pd.DataFrame, bar_type: BarType, fiyat_hassasiyeti: int = 2,
           miktar_hassasiyeti: int = 6) -> list[Bar]:
    """(tarih, acilis, max, min, kapanis, hacim) DataFrame → [Bar]."""
    gerekli = {"tarih", "acilis", "max", "min", "kapanis", "hacim"}
    eksik = gerekli - set(df.columns)
    if eksik:
        raise ValueError(f"OHLCV kolonları eksik: {sorted(eksik)}")
    out: list[Bar] = []
    for r in df.itertuples(index=False):
        ts = int(pd.Timestamp(r.tarih).value)  # nanosaniye
        out.append(
            Bar(
                bar_type=bar_type,
                open=Price(float(r.acilis), fiyat_hassasiyeti),
                high=Price(float(r.max), fiyat_hassasiyeti),
                low=Price(float(r.min), fiyat_hassasiyeti),
                close=Price(float(r.kapanis), fiyat_hassasiyeti),
                volume=Quantity(float(r.hacim), miktar_hassasiyeti),
                ts_event=ts,
                ts_init=ts,
            )
        )
    return out


def yfinance_ohlcv(sembol: str, baslangic: str = "2023-01-01", bitis: str | None = None, periyot: str = "1d") -> pd.DataFrame:
    """BIST/Yahoo Finance'tan OHLCV çekip panel formatına (tarih, acilis, max, min, kapanis, hacim) çevirir."""
    import yfinance as yf

    df = yf.download(sembol, start=baslangic, end=bitis, interval=periyot, progress=False, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError(f"Veri gelmedi: {sembol}")
    df = df.reset_index()
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df.rename(columns={"Date": "tarih", "Datetime": "tarih", "Open": "acilis", "High": "max",
                            "Low": "min", "Close": "kapanis", "Volume": "hacim"})
    return df[["tarih", "acilis", "max", "min", "kapanis", "hacim"]].dropna().reset_index(drop=True)
