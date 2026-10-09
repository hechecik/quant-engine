"""ICT stratejisi — PineScript ICT mantığının NautilusTrader'a taşınmış hâli.

Sinyal kaynağı: quantlib/ict.py (panel tarayıcısıyla AYNI mantık).
Giriş: taze MSS (yapı kırılımı) veya ICT skoru ≥ eşik.
Çıkış: ATR tabanlı stop + hedef (motor içi stop_market/limit emirleri) + ters sinyal.
"""
from __future__ import annotations

import pandas as pd
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from quantlib.ict import ict_hesapla


class IctStratejiConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId = None
    bar_type: BarType = None
    giris_esigi: int = 3          # ICT skoru ≥ eşik → giriş (panel ile aynı: 3)
    mss_girisi: bool = True       # taze MSS tek başına giriş tetikler (ICT mantığı)
    izin_short: bool = False      # BIST hissede açığa satış yok → False
    tahsis: float = 0.95          # bakiyenin işleme ayrılan oranı
    atr_stop: float = 2.0         # stop = giriş ∓ 2×ATR
    atr_hedef: float = 3.0        # hedef = giriş ± 3×ATR
    min_pencere: int = 60         # ICT hesabı için minimum bar sayısı


class IctStrateji(Strategy):
    def __init__(self, config: IctStratejiConfig) -> None:
        super().__init__(config)
        self._rows: list[dict] = []
        self._son_mss_bar = -1
        self._giris_fiyat = 0.0
        self._atr = 0.0
        self._aktif_miktar = None
        self._son_yon = None
        self._sl_id = None
        self._tp_id = None
        self.sinyaller: list[dict] = []

    # ── yaşam döngüsü ──────────────────────────────────────────────
    def on_start(self) -> None:
        self.instr = self.cache.instrument(self.config.instrument_id)
        if self.instr is None:
            raise RuntimeError(f"Enstrüman bulunamadı: {self.config.instrument_id}")
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        self._rows.append({
            "tarih": pd.Timestamp(bar.ts_event, unit="ns"),
            "acilis": bar.open.as_double(), "max": bar.high.as_double(),
            "min": bar.low.as_double(), "kapanis": bar.close.as_double(),
            "hacim": bar.volume.as_double(),
        })
        if len(self._rows) < self.config.min_pencere:
            return
        df = pd.DataFrame(self._rows)
        s = ict_hesapla(df)
        if not s:
            return
        skor = s.get("skor", 0)
        m = s.get("mss") or {}
        yon = m.get("yon")
        atr = float(s.get("atr") or 0.0)
        # taze MSS: bu barın konumundaki yapı kırılımı
        taze_mss = False
        if yon and m.get("bar") is not None:
            if int(m["bar"]) != self._son_mss_bar:
                self._son_mss_bar = int(m["bar"])
                taze_mss = True

        iid = self.config.instrument_id
        uzun = self.portfolio.is_net_long(iid)
        kisa = self.portfolio.is_net_short(iid)
        duz = self.portfolio.is_flat(iid)

        # 1) çıkış: ters sinyal netleşince kapat
        if uzun and (skor <= -self.config.giris_esigi):
            self._kapat("ters sinyal (skor≤%d)" % -self.config.giris_esigi, bar.ts_event)
            return
        if kisa and (skor >= self.config.giris_esigi):
            self._kapat("ters sinyal (skor≥%d)" % self.config.giris_esigi, bar.ts_event)
            return

        # 2) giriş
        if duz:
            uzun_tetik = (skor >= self.config.giris_esigi) or (self.config.mss_girisi and taze_mss and yon == "BULLISH")
            kisa_tetik = (skor <= -self.config.giris_esigi) or (self.config.mss_girisi and taze_mss and yon == "BEARISH")
            if uzun_tetik:
                self._gir(OrderSide.BUY, atr, s, bar.ts_event, skor)
            elif kisa_tetik and self.config.izin_short:
                self._gir(OrderSide.SELL, atr, s, bar.ts_event, skor)

    def on_position_opened(self, event) -> None:
        # giriş doldu → stop + hedef emirleri (motor içi, OCO mantığı)
        self._giris_fiyat = self._rows[-1]["kapanis"]
        if self._atr <= 0 or self._aktif_miktar is None or self._son_yon is None:
            return
        p = self.instr.price_precision
        qty = self._aktif_miktar
        if self._son_yon == OrderSide.BUY:
            karsi = OrderSide.SELL
            sl_px = max(0.01, self._giris_fiyat - self.config.atr_stop * self._atr)
            tp_px = self._giris_fiyat + self.config.atr_hedef * self._atr
        else:
            karsi = OrderSide.BUY
            sl_px = self._giris_fiyat + self.config.atr_stop * self._atr
            tp_px = max(0.01, self._giris_fiyat - self.config.atr_hedef * self._atr)
        self.submit_order(self.order_factory.stop_market(
            self.config.instrument_id, karsi, qty, Price(sl_px, p)))
        self.submit_order(self.order_factory.limit(
            self.config.instrument_id, karsi, qty, Price(tp_px, p)))

    def on_position_closed(self, event) -> None:
        # kalan (eşleşmeyen) stop/hedef emrini iptal et
        for o in self.cache.orders_open(instrument_id=self.config.instrument_id):
            self.cancel_order(o)
        self._sl_id = self._tp_id = None

    def on_stop(self) -> None:
        self.close_all_positions(self.config.instrument_id)

    # ── yardımcılar ────────────────────────────────────────────────
    def _miktar(self, fiyat: float) -> Quantity:
        hesap = self.portfolio.account(self.config.instrument_id.venue)
        bakiye = hesap.balance_free(self.instr.quote_currency).as_double()
        ham = (bakiye * self.config.tahsis) / max(fiyat, 1e-9)
        if self.instr.size_precision == 0:
            return Quantity(max(1, int(ham)), 0)
        return Quantity(round(ham, self.instr.size_precision), self.instr.size_precision)

    def _gir(self, yon: OrderSide, atr: float, s: dict, ts: int, skor: int) -> None:
        fiyat = self._rows[-1]["kapanis"]
        self._atr = atr
        self._giris_fiyat = fiyat
        self._son_yon = yon
        self._aktif_miktar = self._miktar(fiyat)
        self.sinyaller.append({"ts": int(ts), "yon": yon.name, "fiyat": round(fiyat, 2),
                               "skor": skor, "atr": round(atr, 4), "neden": (s.get("nedenler") or [])[:3]})
        self.submit_order(self.order_factory.market(self.config.instrument_id, yon, self._aktif_miktar))

    def _kapat(self, neden: str, ts: int) -> None:
        self.sinyaller.append({"ts": int(ts), "yon": "KAPAT", "neden": neden})
        self.close_all_positions(self.config.instrument_id)
