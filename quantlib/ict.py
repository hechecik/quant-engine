"""ICT indikatör seti — Pine Script mantığının Python'a çevrimi.

Kaynak mantık: ArunKBhaskar/PineScript (MPL-2.0) — TradingView Pine v5 dosyaları
(ICT MSS, FVG Scanner, Liquidity Sweep, Mitigation Block, Order Block Retracement,
Liquidity Void, Equal Highs/Lows, Market Profile, Displacement Candles).
Orijinal kod TradingView'de çalışır; burada AYNI kurallar sıfırdan Python'a yazıldı.

ANTİ-HALLÜSİNASYON KURALI:
  Her sinyal kodda AÇIK bir koşuldan üretilir. Yorum/öngörü uydurulmaz.
  Hesaplanan seviye ve eşik değerleri açıklama metnine yazılır.

Sütun sözleşmesi (kanonik): open, high, low, close, volume
  BIST verisi HGDG_* adlarıyla gelir → hazirla() ile çevir.

Skor kuralı (deterministik — kod aşağıda birebir uygular):
  MSS BULLISH +2 / BEARISH -2
  Displacement mum BULLISH +1 / BEARISH -1
  Kapanış bullish FVG bölgesi İÇİNDE +1 / bearish FVG içinde -1
  Kapanış bullish Order Block bölgesi içinde (tap) +1 / bearish OB tap -1
  Likidite süpürmesi BULLISH +1 / BEARISH -1
  Kapanış Value Area ÜSTÜNDE +1 / ALTINDA -1
  Eşik: skor >= 3 AL, <= -3 SAT, arası TUT.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ─────────────────────────── yardımcılar ───────────────────────────

def hazirla(df: pd.DataFrame) -> pd.DataFrame:
    """HGDG_* (BIST) veya büyük/küçük harfli sütunları kanonik ada çevirir."""
    m = {
        'HGDG_MAX': 'high', 'HGDG_MIN': 'low', 'HGDG_KAPANIS': 'close',
        'HGDG_HACIM': 'volume', 'High': 'high', 'Low': 'low',
        'Close': 'close', 'Open': 'open', 'Volume': 'volume',
        'max': 'high', 'min': 'low', 'kapanis': 'close',
        'acilis': 'open', 'hacim': 'volume',
    }
    d = df.rename(columns={k: v for k, v in m.items() if k in df.columns}).copy()
    if 'open' not in d.columns:
        d['open'] = d['close'].shift(1).fillna(d['close'])
    if 'volume' not in d.columns:
        d['volume'] = 0.0
    for c in ('open', 'high', 'low', 'close', 'volume'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    return d.dropna(subset=['high', 'low', 'close']).reset_index(drop=True)


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df['close'].shift(1)
    tr = pd.concat([df['high'] - df['low'],
                    (df['high'] - pc).abs(),
                    (df['low'] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


# ─────────────────────────── ZigZag (swing) ───────────────────────────

def zigzag(df: pd.DataFrame, donem: int = 4, min_yuzde: float = 0.7) -> list[dict]:
    """Pine 'Zig Zag Ratio' mantığı: ±donem penceresinde uç + min % hareket filtresi.

    Dönen pivotlar: {'idx','tip' ('H'|'L'),'fiyat'}. Kronolojik sırada.
    """
    high = df['high'].values
    low = df['low'].values
    n = len(df)
    aday = []
    for i in range(donem, n - donem):
        wl = low[i - donem:i + donem + 1]
        wh = high[i - donem:i + donem + 1]
        if high[i] >= wh.max() and (wh.argmax() == donem):
            aday.append({'idx': i, 'tip': 'H', 'fiyat': float(high[i])})
        elif low[i] <= wl.min() and (wl.argmin() == donem):
            aday.append({'idx': i, 'tip': 'L', 'fiyat': float(low[i])})

    # aynı tip ardışıkları sadeleştir + min % filtre
    piv = []
    for p in aday:
        if not piv:
            piv.append(p)
            continue
        son = piv[-1]
        if p['tip'] == son['tip']:
            if (p['tip'] == 'H' and p['fiyat'] >= son['fiyat']) or \
               (p['tip'] == 'L' and p['fiyat'] <= son['fiyat']):
                piv[-1] = p
        else:
            degisim = abs(p['fiyat'] - son['fiyat']) / son['fiyat'] * 100 if son['fiyat'] else 0
            if degisim >= min_yuzde:
                piv.append(p)
    return piv


# ─────────────────────────── MSS (Market Structure Shift) ───────────────────────────

def mss(df: pd.DataFrame, piv: list[dict] | None = None, son_bar: int = 6) -> dict:
    """Yapı kırılımı: son `son_bar` bar içinde fiyat, o an yürürlükte olan son swing
    high'ı yukarı / swing low'u aşağı kırdı mı (ICT Market Structure Shift / BOS)."""
    piv = piv if piv is not None else zigzag(df)
    if len(piv) < 2:
        return {}
    close = df['close'].values
    n = len(df)
    for j in range(max(1, n - son_bar), n):
        onceki = [p for p in piv if p['idx'] < j]
        if len(onceki) < 2:
            continue
        sh = [p for p in onceki if p['tip'] == 'H']
        sl = [p for p in onceki if p['tip'] == 'L']
        if sh:
            son_sh = sh[-1]
            if close[j] > son_sh['fiyat']:
                return {'yon': 'BULLISH', 'seviye': round(son_sh['fiyat'], 2), 'bar': n - 1 - j,
                        'aciklama': f"{n - 1 - j} bar önce kapanış ({close[j]:.2f}) son swing yükseğini "
                                    f"({son_sh['fiyat']:.2f}) kırdı → yapı yukarı döndü (MSS/BOS)"}
        if sl:
            son_sl = sl[-1]
            if close[j] < son_sl['fiyat']:
                return {'yon': 'BEARISH', 'seviye': round(son_sl['fiyat'], 2), 'bar': n - 1 - j,
                        'aciklama': f"{n - 1 - j} bar önce kapanış ({close[j]:.2f}) son swing dibini "
                                    f"({son_sl['fiyat']:.2f}) kırdı → yapı aşağı döndü (MSS/BOS)"}
    return {}


# ─────────────────────────── Fair Value Gap ───────────────────────────

def fvg(df: pd.DataFrame, tara: int = 30) -> dict:
    """3-mum boşluğu. Son `tara` bar içinde EN GÜNCEL açık FVG'yi döndürür."""
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    n = len(df)
    c = float(close[-1])
    for i in range(n - 1, max(1, n - 1 - tara), -1):
        if i - 2 < 0:
            break
        if low[i] > high[i - 2]:                      # bullish FVG
            alt, ust = float(high[i - 2]), float(low[i])
            doldu = bool(low[i + 1:].min() <= alt) if i + 1 < n else False
            return {'yon': 'BULLISH', 'alt': round(alt, 2), 'ust': round(ust, 2),
                    'durum': 'DOLDU' if doldu else 'AÇIK',
                    'konum': 'İÇİNDE' if alt <= c <= ust else ('ÜSTÜNDE' if c > ust else 'ALTINDA'),
                    'aciklama': f"bullish FVG {alt:.2f}–{ust:.2f} (bar -{n - 1 - i})"}
        if high[i] < low[i - 2]:                      # bearish FVG
            alt, ust = float(high[i]), float(low[i - 2])
            doldu = bool(high[i + 1:].max() >= ust) if i + 1 < n else False
            return {'yon': 'BEARISH', 'alt': round(alt, 2), 'ust': round(ust, 2),
                    'durum': 'DOLDU' if doldu else 'AÇIK',
                    'konum': 'İÇİNDE' if alt <= c <= ust else ('ÜSTÜNDE' if c > ust else 'ALTINDA'),
                    'aciklama': f"bearish FVG {alt:.2f}–{ust:.2f} (bar -{n - 1 - i})"}
    return {}


# ─────────────────────────── Displacement ───────────────────────────

def displacement(df: pd.DataFrame, atr: pd.Series | None = None, k: float = 1.2) -> dict:
    """Güçlü momentum mumu: gövde > ATR*k ve gövde/aralık > 0.6 (tek yönlü hareket)."""
    atr = atr if atr is not None else _atr(df)
    if atr.isna().all() or float(atr.iloc[-1]) == 0:
        return {}
    o = df['open'].values
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    i = len(df) - 1
    govde = abs(c[i] - o[i])
    aralik = h[i] - l[i]
    a = float(atr.iloc[-1])
    if aralik <= 0 or govde < a * k or govde / aralik < 0.6:
        return {}
    yon = 'BULLISH' if c[i] > o[i] else 'BEARISH'
    return {'yon': yon, 'bar_govde': round(govde, 2), 'atr': round(a, 2),
            'aciklama': f"{'alıcı' if yon == 'BULLISH' else 'satıcı'} displacement mumu — "
                        f"gövde {govde:.2f} > ATR×{k} ({a * k:.2f})"}


# ─────────────────────────── Order Block / Mitigation Block ───────────────────────────

def order_block(df: pd.DataFrame, atr: pd.Series | None = None, tara: int = 40, k: float = 1.2) -> dict:
    """Displacement mumundan ÖNCEKİ ters yönlü mum = Order Block.

    Bullish OB: güçlü yeşil mumdan önceki kırmızı mumun [low, open] aralığı.
    Bearish OB: güçlü kırmızı mumdan önceki yeşil mumun [open, high] aralığı.
    durum: 'İÇİNDE' (fiyat OB bölgesinde — retracement girişi),
           'MİTİGASYON' (bölge kullanıldı/geçildi), 'UZAK'.
    """
    atr = atr if atr is not None else _atr(df)
    o = df['open'].values
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    n = len(df)
    fiyat = float(c[-1])
    for i in range(n - 1, max(1, n - 1 - tara), -1):
        a = float(atr.iloc[i])
        if a <= 0:
            continue
        govde = abs(c[i] - o[i])
        if govde < a * k:
            continue
        onceki = i - 1
        if c[i] > o[i] and c[onceki] < o[onceki]:          # bullish displacement → bullish OB
            alt, ust = float(l[onceki]), float(o[onceki])
            durum = 'İÇİNDE' if alt <= fiyat <= ust else ('MİTİGASYON' if fiyat > ust else 'UZAK')
            return {'yon': 'BULLISH', 'alt': round(alt, 2), 'ust': round(ust, 2), 'durum': durum,
                    'displacement_bar': n - 1 - i,
                    'aciklama': f"bullish Order Block {alt:.2f}–{ust:.2f} (displacement -{n - 1 - i} bar)"}
        if c[i] < o[i] and c[onceki] > o[onceki]:          # bearish displacement → bearish OB
            alt, ust = float(o[onceki]), float(h[onceki])
            durum = 'İÇİNDE' if alt <= fiyat <= ust else ('MİTİGASYON' if fiyat < alt else 'UZAK')
            return {'yon': 'BEARISH', 'alt': round(alt, 2), 'ust': round(ust, 2), 'durum': durum,
                    'displacement_bar': n - 1 - i,
                    'aciklama': f"bearish Order Block {alt:.2f}–{ust:.2f} (displacement -{n - 1 - i} bar)"}
    return {}


# ─────────────────────────── Likidite süpürmesi ───────────────────────────

def likidite_supurme(df: pd.DataFrame, donem: int = 20, son_bar: int = 4) -> dict:
    """Son `son_bar` bar içinde, `donem` barlık dip/direnç kırıldı ama kapanış geri
    döndü mü (ICT liquidity sweep / stop avı). En güncel süpürmeyi döndürür."""
    if len(df) < donem + son_bar + 2:
        return {}
    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
    n = len(df)
    for i in range(n - son_bar, n):
        if i - donem < 1:
            continue
        ph = float(h[i - donem:i].max())
        pl = float(l[i - donem:i].min())
        orta = (h[i] + l[i]) / 2.0
        if l[i] < pl and c[i] > pl and c[i] > orta:
            return {'yon': 'BULLISH', 'seviye': round(pl, 2), 'bar': n - 1 - i,
                    'aciklama': f"{n - 1 - i} bar önce destek {pl:.2f} süpürüldü, kapanış üstüne "
                                f"döndü ({c[i]:.2f}) → aşağı tuzak"}
        if h[i] > ph and c[i] < ph and c[i] < orta:
            return {'yon': 'BEARISH', 'seviye': round(ph, 2), 'bar': n - 1 - i,
                    'aciklama': f"{n - 1 - i} bar önce direnç {ph:.2f} süpürüldü, kapanış altına "
                                f"döndü ({c[i]:.2f}) → yukarı tuzak"}
    return {}


# ─────────────────────────── Equal Highs / Lows ───────────────────────────

def eqh_eql(df: pd.DataFrame, piv: list[dict] | None = None, tolerans_atr: float = 0.6) -> dict:
    """Eşit yüksekler/düşükler = üst üste birikmiş likidite havuzu (stop bölgesi).

    Tolerans ATR tabanlı (tolerans_atr × ATR) — sabit % yerine volatiliteye uyarlanır.
    """
    piv = piv if piv is not None else zigzag(df)
    atr = float(_atr(df).iloc[-1])
    tol = atr * tolerans_atr
    fiyat = float(df['close'].iloc[-1])
    out = {}
    highs = [p for p in piv if p['tip'] == 'H']
    lows = [p for p in piv if p['tip'] == 'L']
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if abs(a['fiyat'] - b['fiyat']) <= tol:
            sev = round((a['fiyat'] + b['fiyat']) / 2, 2)
            out['eqh'] = {'seviye': sev, 'mesafe_yuzde': round((sev - fiyat) / fiyat * 100, 2),
                          'aciklama': f"eşit yüksekler ≈ {sev} (fiyata %{round((sev - fiyat) / fiyat * 100, 2)}) "
                                      f"→ üstte likidite havuzu, süpürme hedefi"}
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if abs(a['fiyat'] - b['fiyat']) <= tol:
            sev = round((a['fiyat'] + b['fiyat']) / 2, 2)
            out['eql'] = {'seviye': sev, 'mesafe_yuzde': round((fiyat - sev) / fiyat * 100, 2),
                          'aciklama': f"eşit düşükler ≈ {sev} (fiyata %{round((fiyat - sev) / fiyat * 100, 2)}) "
                                      f"→ altta likidite havuzu, süpürme hedefi"}
    return out


# ─────────────────────────── Liquidity Void ───────────────────────────

def likidite_voydu(df: pd.DataFrame, atr: pd.Series | None = None, k: float = 1.8) -> dict:
    """Likitide boşluğu: tek mumda hızlı, geri dönüşsüz hareket (gövde/aralık > 0.75)."""
    atr = atr if atr is not None else _atr(df)
    o = df['open'].values
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    i = len(df) - 1
    a = float(atr.iloc[-1])
    govde = abs(c[i] - o[i])
    aralik = h[i] - l[i]
    if a <= 0 or aralik <= 0 or govde < a * k or govde / aralik < 0.75:
        return {}
    yon = 'BULLISH' if c[i] > o[i] else 'BEARISH'
    return {'yon': yon, 'alt': round(float(min(o[i], c[i])), 2), 'ust': round(float(max(o[i], c[i])), 2),
            'aciklama': f"likidite boşluğu — tek mumda {govde:.2f} puan hareket (gövde/aralık "
                        f"{govde / aralik:.2f}), geri dönüşsüz bölge"}


# ─────────────────────────── Market Profile ───────────────────────────

def market_profile(df: pd.DataFrame, geriye: int = 60, bins: int = 30, va_oran: float = 0.70) -> dict:
    """Hacim-fiyat dağılımı: POC (en çok hacim), VAH/VAL (hacmin %70'i)."""
    d = df.tail(geriye)
    if len(d) < 10:
        return {}
    h, l, c, v = d['high'].values, d['low'].values, d['close'].values, d['volume'].values
    if float(np.nansum(v)) <= 0:      # hacim yoksa kapanış ağırlığı
        v = np.ones_like(c)
    alt, ust = float(np.nanmin(l)), float(np.nanmax(h))
    if ust <= alt:
        return {}
    kenar = np.linspace(alt, ust, bins + 1)
    hist = np.zeros(bins)
    for hi, lo, vi in zip(h, l, v):
        if not np.isfinite(hi) or not np.isfinite(lo):
            continue
        b0 = int(np.clip(np.searchsorted(kenar, lo, 'right') - 1, 0, bins - 1))
        b1 = int(np.clip(np.searchsorted(kenar, hi, 'right') - 1, 0, bins - 1))
        if b1 < b0:
            b0, b1 = b1, b0
        pay = (vi if np.isfinite(vi) else 0) / (b1 - b0 + 1)
        hist[b0:b1 + 1] += pay
    toplam = hist.sum()
    if toplam <= 0:
        return {}
    poc_i = int(hist.argmax())
    # value area: POC'tan dışa doğru %70 hacme ulaşana dek genişlet
    sol = sag = poc_i
    kapsam = hist[poc_i]
    while kapsam < toplam * va_oran and (sol > 0 or sag < bins - 1):
        s = hist[sol - 1] if sol > 0 else -1
        g = hist[sag + 1] if sag < bins - 1 else -1
        if g >= s:
            sag += 1
            kapsam += hist[sag]
        else:
            sol -= 1
            kapsam += hist[sol]
    fiyat = float(c[-1])
    vah, val = float(kenar[sag + 1]), float(kenar[sol])
    konum = 'VA ÜSTÜ' if fiyat > vah else ('VA ALTI' if fiyat < val else 'VA İÇİ')
    return {'poc': round(float(kenar[poc_i] + kenar[poc_i + 1]) / 2, 2),
            'vah': round(vah, 2), 'val': round(val, 2), 'konum': konum,
            'aciklama': f"Market Profile: POC {round(float(kenar[poc_i] + kenar[poc_i + 1]) / 2, 2)}, "
                        f"değer alanı {val:.2f}–{vah:.2f} → fiyat {konum}"}


# ─────────────────────────── ana hesaplayıcı ───────────────────────────

def ict_hesapla(df: pd.DataFrame, donem_zigzag: int = 4) -> dict:
    """Tüm ICT setini hesapla + deterministik skor/sinyal üret. df kanonik sütunlu olmalı."""
    if len(df) < 30:
        return {}
    d = hazirla(df) if 'high' not in df.columns else df.reset_index(drop=True)
    atr = _atr(d)
    piv = zigzag(d, donem=donem_zigzag)
    sonuc = {
        'mss': mss(d, piv),
        'fvg': fvg(d),
        'ob': order_block(d, atr),
        'displacement': displacement(d, atr),
        'sweep': likidite_supurme(d),
        'voy': likidite_voydu(d, atr),
        'profile': market_profile(d),
        'pivots': len(piv),
    }
    sonuc.update(eqh_eql(d, piv))

    fiyat = float(d['close'].iloc[-1])
    skor = 0
    neden = []

    m = sonuc.get('mss') or {}
    if m.get('yon') == 'BULLISH':
        skor += 2
        neden.append(f"MSS↑ {m['aciklama']}")
    elif m.get('yon') == 'BEARISH':
        skor -= 2
        neden.append(f"MSS↓ {m['aciklama']}")

    dp = sonuc.get('displacement') or {}
    if dp.get('yon') == 'BULLISH':
        skor += 1
        neden.append(f"Displacement↑ {dp['aciklama']}")
    elif dp.get('yon') == 'BEARISH':
        skor -= 1
        neden.append(f"Displacement↓ {dp['aciklama']}")

    f = sonuc.get('fvg') or {}
    if f.get('konum') == 'İÇİNDE':
        if f.get('yon') == 'BULLISH':
            skor += 1
            neden.append(f"Fiyat bullish FVG içinde ({f['alt']}–{f['ust']}) → destek bölgesi")
        else:
            skor -= 1
            neden.append(f"Fiyat bearish FVG içinde ({f['alt']}–{f['ust']}) → direnç bölgesi")

    ob = sonuc.get('ob') or {}
    if ob.get('durum') == 'İÇİNDE':
        if ob.get('yon') == 'BULLISH':
            skor += 1
            neden.append(f"Fiyat bullish Order Block içinde ({ob['alt']}–{ob['ust']}) → talep bölgesi")
        else:
            skor -= 1
            neden.append(f"Fiyat bearish Order Block içinde ({ob['alt']}–{ob['ust']}) → arz bölgesi")

    sw = sonuc.get('sweep') or {}
    if sw.get('yon') == 'BULLISH':
        skor += 1
        neden.append(f"Likidite süpürmesi↑ {sw['aciklama']}")
    elif sw.get('yon') == 'BEARISH':
        skor -= 1
        neden.append(f"Likidite süpürmesi↓ {sw['aciklama']}")

    pr = sonuc.get('profile') or {}
    if pr.get('konum') == 'VA ÜSTÜ':
        skor += 1
        neden.append(f"Fiyat değer alanı üstünde (VAH {pr['vah']}) → kabul/güç")
    elif pr.get('konum') == 'VA ALTI':
        skor -= 1
        neden.append(f"Fiyat değer alanı altında (VAL {pr['val']}) → red/zayıflık")

    if sonuc.get('eqh'):
        neden.append(sonuc['eqh']['aciklama'])
    if sonuc.get('eql'):
        neden.append(sonuc['eql']['aciklama'])
    if (sonuc.get('voy') or {}).get('yon'):
        neden.append((sonuc['voy'])['aciklama'])

    sinyal = 'AL' if skor >= 3 else ('SAT' if skor <= -3 else 'TUT')
    sonuc.update({'skor': skor, 'sinyal': sinyal, 'fiyat': round(fiyat, 2),
                  'atr': round(float(atr.iloc[-1]), 4) if len(atr) else 0.0,
                  'nedenler': neden[:6]})
    return sonuc


if __name__ == '__main__':
    import json
    import sys
    # hızlı kendi kendini test: sentetik veri (rastgele yürüyüş + bilinen FVG)
    rng = np.random.default_rng(7)
    fiyat = 100.0
    rows = []
    for t in range(120):
        o = fiyat
        fiyat *= 1 + rng.normal(0, 0.012)
        c = fiyat
        h = max(o, c) * (1 + abs(rng.normal(0, 0.004)))
        l = min(o, c) * (1 - abs(rng.normal(0, 0.004)))
        rows.append({'open': o, 'high': h, 'low': l, 'close': c, 'volume': float(rng.integers(1e5, 1e6))})
    df = pd.DataFrame(rows)
    print(json.dumps(ict_hesapla(df), ensure_ascii=False, indent=2, default=str))
