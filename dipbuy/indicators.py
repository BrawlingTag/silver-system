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


def rsi_cross_up(r: pd.Series, ma: int) -> pd.Series:
    """Tage, an denen der RSI von unten über seinen gleitenden Durchschnitt kreuzt."""
    m = r.rolling(ma).mean()
    return (r > m) & (r.shift(1) <= m.shift(1))


def rules(close: pd.Series, dip_pct: float = None, window: int = None, rsi_ma: int = None,
          hold: int = None, exit_below: float = None) -> pd.DataFrame:
    """Die drei Kaufregeln und die Verkaufsregel für jeden Handelstag.

    Kauf, wenn am selben Tag gilt:
      1. dip:   Index war in den letzten `window` Tagen mindestens `dip_pct` % unter dem 52-Wochen-Hoch
      2. trend: Index schließt über seiner 200-Tage-Linie
      3. turn:  RSI kreuzt über seinen `rsi_ma`-Tage-Schnitt
    Verkauf, wenn der Index mehr als `exit_below` % unter seiner 200-Tage-Linie schließt.
    Wiedereinstieg: der erste Tag nach einem Verkauf, an dem der Index wieder über der Linie schließt.
    """
    dip_pct = config.DIP_PCT if dip_pct is None else dip_pct
    window = window or config.DIP_WINDOW
    rsi_ma = rsi_ma or config.RSI_MA
    hold = hold or config.SIGNAL_HOLD
    exit_below = config.EXIT_BELOW if exit_below is None else exit_below

    close = close.dropna()
    sma = close.rolling(200).mean()
    dd = drawdown(close)
    r = rsi(close)
    out = pd.DataFrame({
        "close": close,
        "sma200": sma,
        "distance": (close / sma - 1) * 100,
        "drawdown": dd,
        "drawdown_max": dd.rolling(window, min_periods=1).max(),
        "rsi": r,
        "rsi_ma": r.rolling(rsi_ma).mean(),
    })
    out["dip"] = out["drawdown_max"] >= dip_pct
    out["trend"] = close > sma
    out["turn"] = rsi_cross_up(r, rsi_ma)
    out["buy"] = out["dip"] & out["trend"] & out["turn"]
    out["turn_recent"] = out["turn"].astype(float).rolling(hold, min_periods=1).max().astype(bool)
    out["buy_recent"] = out["buy"].astype(float).rolling(hold, min_periods=1).max().astype(bool)
    out["below"] = out["distance"] < -exit_below
    out["sell"] = out["below"] & ~out["below"].shift(1, fill_value=False)
    # Nach einem Verkauf "draußen", bis der Index wieder über der Linie schließt
    out_state = pd.Series(np.nan, index=out.index).mask(out["below"], 1.0).mask(out["trend"], 0.0).ffill()
    out["reentry"] = out["trend"] & (out_state.shift(1) == 1.0)
    out["reentry_recent"] = out["reentry"].astype(float).rolling(hold, min_periods=1).max().astype(bool)
    return out


def status(row) -> dict:
    """Ampel für den heutigen Tag aus einer Zeile von `rules`."""
    if pd.isna(row["sma200"]):
        return {"color": "grey", "label": "Keine Daten", "text": "Zu wenig Kursdaten."}
    if row["below"]:
        return {"color": "red", "label": "Verkaufen",
                "text": f"Der Nasdaq 100 liegt mehr als {config.EXIT_BELOW:g} % unter seiner 200-Tage-Linie. "
                        "Hebel raus, keine Neukäufe."}
    if row["reentry_recent"]:
        return {"color": "green", "label": "Wieder einsteigen",
                "text": "Der Nasdaq 100 ist nach dem Verkauf zurück über seiner 200-Tage-Linie. Hebel wieder kaufen."}
    if row["buy_recent"]:
        return {"color": "green", "label": "Kaufen",
                "text": "Alle drei Regeln sind erfüllt: Rücksetzer, Aufwärtstrend und der RSI dreht nach oben."}
    if not row["trend"]:
        return {"color": "yellow", "label": "Nicht nachkaufen",
                "text": "Der Nasdaq 100 ist unter seine 200-Tage-Linie gefallen. Halten, aber nichts Neues kaufen."}
    if row["dip"]:
        return {"color": "yellow", "label": "Dip läuft",
                "text": "Rücksetzer im Aufwärtstrend. Warten, bis der RSI nach oben dreht."}
    return {"color": "grey", "label": "Kein Dip",
            "text": f"Halten. Neu gekauft wird erst nach einem Rücksetzer von {config.DIP_PCT:g} %."}


def exit_signal(close: pd.Series, exit_below: float = None) -> dict:
    """Hebel halten, solange der Index nicht mehr als `exit_below` % unter seiner 200-Tage-Linie liegt."""
    exit_below = config.EXIT_BELOW if exit_below is None else exit_below
    close = close.dropna()
    sma200 = close.rolling(200).mean()
    if sma200.dropna().empty:
        return {"hold": None}
    hold = (close / sma200 - 1) * 100 >= -exit_below
    hold = hold[sma200.notna()]
    changed = hold.ne(hold.shift())
    since = int(len(hold) - 1 - np.flatnonzero(changed.to_numpy())[-1])
    return {
        "hold": bool(hold.iloc[-1]),
        "distance": round(float((close.iloc[-1] / sma200.iloc[-1] - 1) * 100), 2),
        "days": since,
        "close": round(float(close.iloc[-1]), 2),
        "sma200": round(float(sma200.iloc[-1]), 2),
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
