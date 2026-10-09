#!/usr/bin/env python3
"""quant-engine — ICT stratejisi backtest çalıştırıcısı.

Örnekler:
  python run_backtest.py --kaynak kripto --sembol BTCUSDT --periyot 1d --limit 800
  python run_backtest.py --kaynak bist  --sembol THYAO  --baslangic 2023-01-01 --bakiye 100000
  python run_backtest.py --kaynak bist  --sembol GARAN  --esik 2 --short
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import TRY, USDT
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import TraderId, Venue
from nautilus_trader.model.objects import Money

from quantlib.kopru import bar_tipi, barlar, bist_enstruman, kripto_enstruman
from quantlib.veri import veri_getir
from strategies.ict_strategy import IctStrateji, IctStratejiConfig


def main() -> int:
    ap = argparse.ArgumentParser(description="ICT stratejisi backtest (Layer 3)")
    ap.add_argument("--kaynak", choices=["kripto", "bist"], required=True)
    ap.add_argument("--sembol", required=True)
    ap.add_argument("--periyot", default="1d", help="1d / 1h / 4h (kripto) · 1d (bist)")
    ap.add_argument("--limit", type=int, default=1000, help="kripto bar sayısı (max 1000)")
    ap.add_argument("--baslangic", default="2023-01-01")
    ap.add_argument("--bitis", default=None)
    ap.add_argument("--bakiye", type=float, default=100_000.0)
    ap.add_argument("--esik", type=int, default=3, help="giriş ICT skor eşiği")
    ap.add_argument("--short", action="store_true", help="açığa satışa izin ver (kripto)")
    ap.add_argument("--cikti", default=None, help="sinyal/rapor JSON yolu")
    a = ap.parse_args()

    print(f"▸ Veri çekiliyor: {a.kaynak} / {a.sembol} …", flush=True)
    df = veri_getir(a.kaynak, a.sembol, baslangic=a.baslangic, bitis=a.bitis, periyot=a.periyot)
    print(f"  {len(df)} bar  ({df['tarih'].iloc[0]} → {df['tarih'].iloc[-1]})", flush=True)

    if a.kaynak == "kripto":
        instr = kripto_enstruman(a.sembol)
        venue, para, hesap_tipi = Venue("BINANCE"), USDT, AccountType.MARGIN
        izin_short = True if a.short else False
    else:
        instr = bist_enstruman(a.sembol)
        venue, para, hesap_tipi = Venue("XIST"), TRY, AccountType.CASH
        izin_short = False

    bt = bar_tipi(instr.id, "1-DAY" if a.periyot.endswith("d") else f"{a.periyot.split('h')[0]}-HOUR")
    bar_listesi = barlar(df, bt, instr.price_precision, instr.size_precision)

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=TraderId("QUANT-ENGINE-001"),
        logging=LoggingConfig(log_level="ERROR"),
    ))
    engine.add_venue(venue=venue, oms_type=OmsType.NETTING, account_type=hesap_tipi,
                     base_currency=None, starting_balances=[Money(a.bakiye, para)])
    engine.add_instrument(instr)
    engine.add_data(bar_listesi)
    strateji = IctStrateji(config=IctStratejiConfig(
        instrument_id=instr.id, bar_type=bt, giris_esigi=a.esik, izin_short=izin_short,
    ))
    engine.add_strategy(strateji)
    engine.run()

    rapor = engine.trader.generate_account_report(venue)
    baslangic_bakiye = a.bakiye
    son_bakiye = float(rapor["total"].iloc[-1]) if not rapor.empty else baslangic_bakiye
    getiri = (son_bakiye / baslangic_bakiye - 1) * 100
    dolum = engine.trader.generate_order_fills_report()
    pr = engine.trader.generate_positions_report()
    kapanan = pr[pr["ts_closed"].notna()] if (pr is not None and len(pr)) else []

    def _pnl(x):
        """'−7994.72 USDT' veya Money → float."""
        try:
            return float(str(x).split()[0])
        except Exception:
            return float(getattr(x, "as_double", lambda: 0.0)())

    kazanan = kapanan[kapanan["realized_pnl"].apply(lambda x: _pnl(x) > 0)] if len(kapanan) else []
    pnl_toplam = sum(_pnl(p) for p in kapanan["realized_pnl"]) if len(kapanan) else 0.0

    ozet = {
        "kaynak": a.kaynak, "sembol": a.sembol.upper(), "periyot": a.periyot,
        "bar_sayisi": len(df), "ilk_bar": str(df["tarih"].iloc[0]), "son_bar": str(df["tarih"].iloc[-1]),
        "baslangic_bakiye": baslangic_bakiye, "son_bakiye": round(son_bakiye, 2),
        "getiri_yuzde": round(getiri, 2), "dolum_sayisi": int(dolum.shape[0]),
        "islem_sayisi": len(kapanan), "kazanan": len(kazanan),
        "isabet_orani": round(100 * len(kazanan) / len(kapanan), 1) if len(kapanan) else None,
        "realize_pnl": round(pnl_toplam, 2),
        "sinyal_sayisi": len(strateji.sinyaller),
        "sinyaller": strateji.sinyaller[:40],
        "motor": "nautilus_trader", "strateji": "ICT (PineScript mantığı → Python)",
        "olusturma": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    print("\n" + "=" * 58)
    print(f"  ICT BACKTEST — {a.sembol.upper()} ({a.kaynak}) · eşik={a.esik} · short={'evet' if izin_short else 'hayır'}")
    print("=" * 58)
    print(f"  Bar             : {len(df)}  ({df['tarih'].iloc[0].date()} → {df['tarih'].iloc[-1].date()})")
    print(f"  Başlangıç       : {baslangic_bakiye:,.2f} {para}")
    print(f"  Son bakiye      : {son_bakiye:,.2f} {para}")
    print(f"  Getiri          : {getiri:+.2f}%")
    print(f"  Emir dolumu     : {int(dolum.shape[0])}")
    print(f"  İşlem (kapanan) : {len(kapanan)}  ·  kazanan {len(kazanan)}"
          f"{'  ·  isabet %' + str(round(100*len(kazanan)/len(kapanan),1)) if len(kapanan) else ''}")
    print(f"  Realize PnL     : {pnl_toplam:+,.2f} {para}")
    print(f"  Sinyal          : {len(strateji.sinyaller)}")
    print("=" * 58)

    if a.cikti:
        with open(a.cikti, "w", encoding="utf-8") as f:
            json.dump(ozet, f, ensure_ascii=False, indent=2)
        print(f"  Rapor → {a.cikti}")
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
