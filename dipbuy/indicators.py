"""Reine Rechenfunktionen auf pandas-Series mit Datumsindex.

Derselbe Code liefert den heutigen Stand und den ganzen Verlauf (für Seite und Backtest).
"""

import numpy as np
import pandas as pd

from . import config


def lin(x, zero, full):
    """0 Punkte bei `zero`, 100 Punkte bei `full`, linear dazwischen, begrenzt auf 0-100."""
    return ((x - zero) / (full - zero)).clip(0, 1) * 100


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100.0).where(gain.notna())


def drawdown(close: pd.Series, window: int = 252) -> pd.Series:
    """Abstand zum Hoch der letzten `window` Tage in Prozent (positiv = unter dem Hoch)."""
    peak = close.rolling(window, min_periods=1).max()
    return (1 - close / peak) * 100


def steps(x: pd.Series, calm: float, threshold: float, extreme: float) -> pd.Series:
    """0 Punkte bei `calm`, 50 an der Schwelle, 100 bei `extreme`, linear dazwischen."""
    return lin(x, calm, threshold) / 2 + lin(x, threshold, extreme) / 2


def recent(flag: pd.Series, window: int) -> pd.Series:
    """War `flag` in den letzten `window` Handelstagen (heute eingeschlossen) mindestens einmal wahr?"""
    return flag.astype(float).rolling(window, min_periods=1).max().astype(bool)


def signals(spx: pd.Series, vix: pd.Series, fear_greed: pd.Series = None, ath_pct: float = None,
            vix_min: float = None, fg_max: float = None, window: int = None, rsi_ma: int = None,
            hold: int = None) -> pd.DataFrame:
    """Kaufsignal und Score für jeden Handelstag.

    Panik, wenn in den letzten `window` Tagen jede dieser Bedingungen erfüllt war:
      1. S&P 500 mindestens `ath_pct` % unter seinem Allzeithoch
      2. VIX über `vix_min`
      3. CNN Fear & Greed unter `fg_max` (Tage ohne CNN-Wert zählen als erfüllt, CNN gibt es nur für wenige Jahre)
    Kauf, wenn außerdem der RSI des S&P 500 heute über dem Schnitt der letzten `rsi_ma` Tage liegt.
    """
    ath_pct = config.ATH_PCT if ath_pct is None else ath_pct
    vix_min = config.VIX_MIN if vix_min is None else vix_min
    fg_max = config.FG_MAX if fg_max is None else fg_max
    window = window or config.SETUP_WINDOW
    rsi_ma = rsi_ma or config.RSI_MA
    hold = hold or config.SIGNAL_HOLD

    spx = spx.dropna()
    idx = spx.index
    vix = vix.reindex(idx).ffill() if vix is not None else pd.Series(np.nan, index=idx)
    fg = (fear_greed.reindex(idx.union(fear_greed.index)).ffill(limit=5).reindex(idx)
          if fear_greed is not None else pd.Series(np.nan, index=idx))
    r = rsi(spx)
    out = pd.DataFrame({
        "close": spx,
        "drawdown": (1 - spx / spx.cummax()) * 100,
        "vix": vix,
        "fear_greed": fg,
        "rsi": r,
        "rsi_ma": sum(r.shift(k) for k in range(1, rsi_ma + 1)) / rsi_ma,
    })
    out["c_drawdown"] = recent(out["drawdown"] >= ath_pct, window)
    out["c_vix"] = recent(out["vix"] > vix_min, window)
    out["c_fear_greed"] = recent(fg.isna() | (fg < fg_max), window)
    out["setup"] = out["c_drawdown"] & out["c_vix"] & out["c_fear_greed"]
    out["turn"] = out["rsi"] > out["rsi_ma"]
    out["buy"] = out["setup"] & out["turn"]
    out["buy_start"] = out["buy"] & ~out["buy"].shift(1, fill_value=False)
    out["buy_recent"] = recent(out["buy"], hold)

    parts = pd.DataFrame({k: steps(out[k], *config.SCORE_PARTS[k]) for k in config.SCORE_PARTS})
    for k in parts:
        out["score_" + k] = parts[k]
    out["score"] = parts.mean(axis=1, skipna=True)
    return out


def hold_state(close: pd.Series, buy: pd.Series = None, exit_below: float = None, hold: int = None) -> pd.DataFrame:
    """Halten oder draußen für jeden Handelstag.

    Verkauf, wenn der Index unter die Marke `exit_below` % unter seiner 200-Tage-Linie fällt.
    Danach draußen, bis er wieder über der Linie schließt (Wiedereinstieg) oder ein Kaufsignal kommt.
    """
    exit_below = config.EXIT_BELOW if exit_below is None else exit_below
    hold = hold or config.SIGNAL_HOLD
    close = close.dropna()
    sma = close.rolling(200).mean()
    out = pd.DataFrame({"close": close, "sma200": sma, "distance": (close / sma - 1) * 100})
    out["below"] = out["distance"] < -exit_below
    out["above"] = out["distance"] > 0
    buy = pd.Series(False, index=close.index) if buy is None else buy.reindex(close.index, fill_value=False)
    falls = out["below"] & ~out["below"].shift(1, fill_value=False)
    state = pd.Series(np.nan, index=close.index).mask(falls, 1.0).mask(out["above"] | buy, 0.0).ffill()
    out["out"] = state == 1.0
    was_out = out["out"].shift(1, fill_value=False)
    out["sell"] = out["out"] & ~was_out
    out["reentry"] = out["above"] & was_out
    out["sell_recent"] = recent(out["sell"], hold)
    out["reentry_recent"] = recent(out["reentry"], hold)
    return out


def status(sig, pos) -> dict:
    """Ampel für den heutigen Tag aus je einer Zeile von `signals` (S&P 500) und `hold_state` (Nasdaq 100)."""
    if pd.isna(sig["rsi"]) or pd.isna(pos["sma200"]):
        return {"color": "grey", "label": "Keine Daten", "text": "Zu wenig Kursdaten."}
    if pos["sell_recent"] and pos["out"]:
        return {"color": "red", "label": "Verkaufen",
                "text": f"Der Nasdaq 100 ist mehr als {config.EXIT_BELOW:g} % unter seine 200-Tage-Linie gefallen. Hebel raus."}
    if sig["buy_recent"]:
        return {"color": "green", "label": "Kaufen",
                "text": "Panik am Markt und der RSI dreht nach oben. Je höher der Score, desto stärker das Signal."}
    if pos["reentry_recent"]:
        return {"color": "green", "label": "Wieder einsteigen",
                "text": "Der Nasdaq 100 ist nach dem Verkauf zurück über seiner 200-Tage-Linie."}
    if sig["setup"]:
        return {"color": "yellow", "label": "Panik, RSI abwarten",
                "text": f"Alle drei Panik-Bedingungen sind erfüllt. Kaufen, sobald der RSI über dem Schnitt "
                        f"der letzten {config.RSI_MA} Tage liegt."}
    if pos["out"]:
        return {"color": "red", "label": "Draußen bleiben",
                "text": "Verkauft. Wieder rein beim nächsten Kaufsignal oder wenn der Nasdaq 100 über seiner 200-Tage-Linie schließt."}
    met = int(sig["c_drawdown"]) + int(sig["c_vix"]) + int(sig["c_fear_greed"])
    return {"color": "grey", "label": "Kein Kaufsignal",
            "text": f"{met} von 3 Panik-Bedingungen erfüllt. Halten, was du hast."}


def exit_signal(close: pd.Series, buy: pd.Series = None, exit_below: float = None) -> dict:
    """Heutiger Stand von `hold_state` für einen Index."""
    st = hold_state(close, buy, exit_below)
    st = st[st["sma200"].notna()]
    if st.empty:
        return {"hold": None}
    hold = ~st["out"]
    changed = hold.ne(hold.shift())
    since = int(len(hold) - 1 - np.flatnonzero(changed.to_numpy())[-1])
    last = st.iloc[-1]
    return {
        "hold": bool(hold.iloc[-1]),
        "distance": round(float(last["distance"]), 2),
        "days": since,
        "close": round(float(last["close"]), 2),
        "sma200": round(float(last["sma200"]), 2),
    }


def stock_score(close: pd.Series, info: dict) -> dict:
    """Score für eine Einzelaktie aus Kurs (Rücksetzer, RSI) und Analystendaten."""
    close = close.dropna()
    price = float(close.iloc[-1])
    dd = float(drawdown(close).iloc[-1])
    r = float(rsi(close).iloc[-1])
    sma200 = close.rolling(200).mean().iloc[-1]

    target = info.get("target")
    upside = (target / price - 1) * 100 if target else None
    rating = info.get("rating")
    revision = info.get("revision")

    def s(v, zero, full):
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(lin(pd.Series([v]), zero, full).iloc[0])

    parts = {
        "drawdown": (s(dd, 5, 40), 25),
        "rsi": (s(r, 55, 25), 15),
        "upside": (s(upside, 5, 40), 20),
        "rating": (s(rating, 3.0, 1.5), 15),
        "revision": (s(revision, -10, 5), 25),
    }
    avail = [(v, w) for v, w in parts.values() if v is not None]
    score = sum(v * w for v, w in avail) / sum(w for _, w in avail) if avail else None
    return {
        "price": round(price, 2),
        "drawdown": round(dd, 1),
        "rsi": round(r, 1),
        "above_sma200": None if np.isnan(sma200) else bool(price > sma200),
        "upside": None if upside is None else round(upside, 1),
        "rating": None if rating is None else round(rating, 2),
        "analysts": info.get("analysts"),
        "revision": None if revision is None else round(revision, 1),
        "score": None if score is None else round(score, 1),
    }
