"""BIST (Borsa İstanbul) custom adapter — NautilusTrader'da yerleşik BIST desteği YOK.

Bu modül, BIST'i NautilusTrader'a bağlayan üç parçayı sağlar:

  1) Enstrüman  : `hisse(...)`  → Equity (XIST, TRY)
  2) Veri       : `BistVeriIstemcisi` → Yahoo Finance (yfinance) OHLCV → Bar
  3) Venue      : `venue_ekle(...)` → nakit hesap, T+2'siz basitleştirilmiş paper yürütme

Canlı (paper) mod: `canli_paper()` gerçek BIST verisini periyodik çeker ve
motorun içine iter — emirler paper hesapta gerçek fiyattan dolar.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.model.currencies import TRY
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money

from quantlib.kopru import bar_tipi, barlar, bist_enstruman
from quantlib.veri import veri_getir

XIST = Venue("XIST")
KOMISYON_ORANI = 0.0002  # ~%0.02 (basitleştirilmiş, aracı kurum komisyonu)


def hisse(sembol: str, isin: str | None = None):
    """BIST hissesi → Equity enstrümanı (fiyat hassasiyeti 2, lot 1)."""
    return bist_enstruman(sembol, fiyat_hassasiyeti=2, isin=isin)


def venue_ekle(engine: BacktestEngine, bakiye_try: float = 1_000_000.0) -> Venue:
    """XIST venue'sini nakit hesap + NETTING OMS ile motora ekler."""
    engine.add_venue(
        venue=XIST,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,      # BIST hisse: kaldıraç yok
        base_currency=TRY,
        starting_balances=[Money(bakiye_try, TRY)],
    )
    return XIST


class BistVeriIstemcisi:
    """Yahoo Finance (<sembol>.IS) üzerinden BIST OHLCV sağlayıcısı."""

    def __init__(self, periyot: str = "1d"):
        self.periyot = periyot

    def tarihsel(self, sembol: str, baslangic: str = "2023-01-01", bitis: str | None = None) -> pd.DataFrame:
        return veri_getir("bist", sembol, baslangic=baslangic, bitis=bitis, periyot=self.periyot)

    def barlar(self, sembol: str, baslangic: str = "2023-01-01", bitis: str | None = None):
        enstruman = hisse(sembol)
        bt = bar_tipi(enstruman.id, "1-DAY" if self.periyot.endswith("d") else "60-MINUTE")
        df = self.tarihsel(sembol, baslangic, bitis)
        return enstruman, bt, barlar(df, bt, enstruman.price_precision, enstruman.size_precision), df

    def son_bar(self, sembol: str):
        """Canlı döngü için: en güncel tamamlanmış günlük barı döndürür."""
        df = self.tarihsel(sembol, baslangic=(datetime.now(timezone.utc).replace(tzinfo=None).year - 1) .__str__() + "-01-01")
        if df.empty:
            return None
        return df.iloc[-1]


def canli_paper(engine: BacktestEngine, sembol: str, periyot_sn: int = 60,
                bitis_ts: int | None = None, maks_deneme: int | None = None) -> None:
    """Gerçek BIST verisini periyodik çekip motora iter (paper trading).

    Not: BacktestEngine'de dış veri `engine.kernel.data_engine.process(bar)` ile
    beslenir. Gerçek canlı yürütme (broker bağlantısı) için NautilusTrader'ın
    `TradingNode` + bir ExecutionClient'ı kullanılır; burada amaç gerçek veriyle
    paper yürütmeyi doğrulamaktır.
    """
    istemci = BistVeriIstemcisi()
    enstruman, bt, _, _ = istemci.barlar(sembol)
    motor_veri = engine.kernel.data_engine
    gorulen: set[int] = set()
    deneme = 0
    print(f"[paper] {sembol} izleniyor ({periyot_sn}s) — Ctrl-C ile dur")
    while True:
        try:
            row = istemci.son_bar(sembol)
            if row is not None:
                ts = int(pd.Timestamp(row["tarih"]).value)
                if ts not in gorulen:
                    from nautilus_trader.model.data import Bar
                    from nautilus_trader.model.objects import Price, Quantity
                    bar = Bar(bt, Price(float(row["acilis"]), 2), Price(float(row["max"]), 2),
                              Price(float(row["min"]), 2), Price(float(row["kapanis"]), 2),
                              Quantity(float(row["hacim"]), 0), ts, ts)
                    motor_veri.process(bar)
                    gorulen.add(ts)
                    print(f"[paper] bar işlendi: {row['tarih']}  kapanış={float(row['kapanis']):.2f}")
                    if bitis_ts and ts >= bitis_ts:
                        break
        except Exception as ex:  # ağ hatası → atla
            print(f"[paper] veri hatası: {ex}")
        deneme += 1
        if maks_deneme and deneme >= maks_deneme:
            break
        time.sleep(periyot_sn)
