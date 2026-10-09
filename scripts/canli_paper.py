#!/usr/bin/env python3
"""Canlı paper yürütme — gerçek BIST/kripto verisi + paper hesap.

Örnek:
  python scripts/canli_paper.py --sembol GARAN --periyot-sn 60
  python scripts/canli_paper.py --kaynak kripto --sembol BTCUSDT --periyot-sn 300

NOT: Gerçek emir GÖNDERİLMEZ. Veri gerçek, hesap paper'dır.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig  # noqa: E402
from nautilus_trader.config import LoggingConfig  # noqa: E402
from nautilus_trader.model.currencies import USDT  # noqa: E402
from nautilus_trader.model.enums import AccountType, OmsType  # noqa: E402
from nautilus_trader.model.identifiers import TraderId, Venue  # noqa: E402
from nautilus_trader.model.objects import Money  # noqa: E402

from bist.adapter import hisse, venue_ekle  # noqa: E402
from quantlib.kopru import bar_tipi, kripto_enstruman  # noqa: E402
from strategies.ict_strategy import IctStrateji, IctStratejiConfig  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="ICT canlı paper yürütme")
    ap.add_argument("--kaynak", choices=["bist", "kripto"], default="bist")
    ap.add_argument("--sembol", default="THYAO")
    ap.add_argument("--periyot-sn", type=int, default=60)
    ap.add_argument("--esik", type=int, default=3)
    ap.add_argument("--short", action="store_true")
    ap.add_argument("--bakiye", type=float, default=1_000_000.0)
    ap.add_argument("--deneme", type=int, default=0, help="N turda dur (0=süresiz, test için)")
    a = ap.parse_args()

    motor = BacktestEngine(config=BacktestEngineConfig(
        trader_id=TraderId("PAPER-001"), logging=LoggingConfig(log_level="ERROR")))

    if a.kaynak == "bist":
        venue = venue_ekle(motor, a.bakiye)
        enstruman = hisse(a.sembol)
        besleyici = "bist"
    else:
        venue = Venue("BINANCE")
        motor.add_venue(venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
                        base_currency=None, starting_balances=[Money(a.bakiye, USDT)])
        enstruman = kripto_enstruman(a.sembol, "BINANCE")
        besleyici = "kripto"

    motor.add_instrument(enstruman)
    bt = bar_tipi(enstruman.id, "1-DAY")
    motor.add_strategy(IctStrateji(config=IctStratejiConfig(
        instrument_id=enstruman.id, bar_type=bt, giris_esigi=a.esik, izin_short=a.short)))
    motor.run()

    print(f"[paper] {a.sembol} · eşik ±{a.esik} · short={'evet' if a.short else 'hayır'}")

    if besleyici == "bist":
        from bist.adapter import canli_paper
        canli_paper(motor, a.sembol, periyot_sn=a.periyot_sn, maks_deneme=a.deneme or None)
    else:
        _kripto_besle(motor, enstruman, bt, a.periyot_sn, a.deneme or None)

    motor.dispose()
    return 0


def _kripto_besle(motor: BacktestEngine, enstruman, bt, periyot_sn: int,
                  maks_deneme: int | None = None) -> None:
    """Binance son fiyatını periyodik çekip bara çevirir (paper)."""
    import json
    import time
    import urllib.request
    from datetime import datetime, timezone

    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.objects import Price, Quantity

    sembol = enstruman.raw_symbol.value
    motor_veri = motor.kernel.data_engine
    gorulen: set[int] = set()
    print(f"[paper] {sembol} izleniyor ({periyot_sn}s) — Ctrl-C ile dur")
    while True:
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={sembol}&interval=1d&limit=1"
            with urllib.request.urlopen(url, timeout=10) as r:
                k = json.load(r)[-1]
            ts = int(k[6]) * 1_000_000  # kapanış zamanı → nanosaniye
            if ts not in gorulen:
                bar = Bar(bt, Price(float(k[1]), 2), Price(float(k[2]), 2), Price(float(k[3]), 2),
                          Price(float(k[4]), 2), Quantity(float(k[5]), 6), ts, ts)
                motor_veri.process(bar)
                gorulen.add(ts)
                print(f"[paper] bar: {datetime.fromtimestamp(ts/1e9, timezone.utc):%Y-%m-%d} kapanış={float(k[4]):,.2f}")
        except Exception as ex:
            print(f"[paper] veri hatası: {ex}")
        time.sleep(periyot_sn)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[paper] durduruldu")
