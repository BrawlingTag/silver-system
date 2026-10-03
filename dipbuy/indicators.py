"""Reine Rechenfunktionen. Jeder Indikator wird auf 0-100 abgebildet (100 = stärkstes Kaufsignal).

Alle Funktionen arbeiten auf pandas-Series mit Datumsindex, damit derselbe Code
den heutigen Wert und den historischen Verlauf liefert.
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


def weighted_mean(parts: dict, weights: dict) -> pd.Series:
    """Gewichteter Mittelwert je Datum; fehlende Werte werden übersprungen."""
    frame = pd.DataFrame(parts)
    w = pd.Series({k: weights[k] for k in frame.columns})
    mask = frame.notna()
    total = (frame.fillna(0) * w).sum(axis=1)
    norm = (mask * w).sum(axis=1)
    return (total / norm.replace(0, np.nan))


ANGST_WEIGHTS = {
    "fear_greed": 1.5, "vix": 1.5, "vix_term": 1.0, "rsi": 1.5,
    "dd_spx": 1.0, "dd_ndx": 1.0, "dd_world": 0.5, "breadth": 1.0,
}
WENDE_WEIGHTS = {"vix_falling": 1.0, "bounce": 1.0}
MAKRO_WEIGHTS = {"hy_level": 1.0, "hy_trend": 1.0, "sahm": 1.0}


def angst_parts(d: dict) -> dict:
    """Wie tief und wie panisch ist der Rücksetzer? Skaliert so, dass schon eine Korrektur
    von rund 6 % deutlich zählt; größere Crashs erreichen schnell die vollen 100.

    d enthält Series: spx, ndx, world, vix, vix3m, fear_greed, breadth (einzelne dürfen None sein).
    """
    p = {}
    if d.get("fear_greed") is not None:
        p["fear_greed"] = lin(d["fear_greed"], 50, 15)
    p["vix"] = lin(d["vix"], 15, 30)
    if d.get("vix3m") is not None:
        p["vix_term"] = lin(d["vix"] / d["vix3m"], 0.85, 1.0)
    # RSI überverkauft zählt sofort, ohne auf den Wiederanstieg zu warten
    p["rsi"] = (lin(rsi(d["spx"]), 50, 25) + lin(rsi(d["ndx"]), 50, 25).reindex(d["spx"].index)) / 2
    p["dd_spx"] = lin(drawdown(d["spx"]), 0, 10)
    p["dd_ndx"] = lin(drawdown(d["ndx"]), 0, 12)
    if d.get("world") is not None:
        p["dd_world"] = lin(drawdown(d["world"]), 0, 10)
    if d.get("breadth") is not None:
        p["breadth"] = lin(d["breadth"], 65, 25)
    return p


def dip_present(spx: pd.Series) -> pd.Series:
    dd = drawdown(spx)
    return dd.rolling(config.DIP_LOOKBACK, min_periods=1).max() >= config.DIP_MIN_DRAWDOWN


def wende_parts(d: dict) -> dict:
    """Frühe Stabilisierung, ohne auf eine bestätigte Wende zu warten: VIX kommt vom Hoch zurück,
    Index erholt sich vom 5-Tage-Tief. Zählt nur nach einem Rücksetzer."""
    vix = d["vix"]
    spx, ndx = d["spx"], d["ndx"].reindex(d["spx"].index)
    bounce = lambda c: lin(c / c.rolling(5, min_periods=1).min() - 1, 0, 0.02)  # noqa: E731
    parts = {
        "vix_falling": lin(1 - vix / vix.rolling(10, min_periods=1).max(), 0, 0.2),
        "bounce": (bounce(spx) + bounce(ndx)) / 2,
    }
    dip = dip_present(d["spx"])
    return {k: v.where(dip, 0.0).where(v.notna()) for k, v in parts.items()}


def makro_parts(d: dict) -> dict:
    """Kreditspreads und Rezessionsrisiko.

    FRED liefert den High-Yield-Spread nur für die letzten drei Jahre. Für ältere Tage springt
    der Spread zwischen Baa-Unternehmensanleihen und 10-jährigen Staatsanleihen (BAA10Y) ein.
    """
    p = {}
    hy, baa = d.get("hy_spread"), d.get("baa_spread")
    if hy is not None or baa is not None:
        level = lin(hy, 8, 4) if hy is not None else None
        trend = lin(hy - hy.shift(20), 1.0, 0.0) if hy is not None else None
        if baa is not None:
            b_level, b_trend = lin(baa, 3.5, 2.0), lin(baa - baa.shift(20), 0.4, 0.0)
            level = b_level if level is None else level.fillna(b_level)
            trend = b_trend if trend is None else trend.fillna(b_trend)
        p["hy_level"], p["hy_trend"] = level, trend
    if d.get("sahm") is not None:
        p["sahm"] = lin(d["sahm"], 0.5, 0.2)
    return p


def credit_stress(d: dict, idx) -> pd.Series:
    """Kreditspreads steigen schnell: High Yield um mehr als 0,75 Pp. oder Baa um mehr als 0,3 Pp. in 20 Tagen."""
    stress = pd.Series(False, index=idx)
    hy, baa = d.get("hy_spread"), d.get("baa_spread")
    hy_known = pd.Series(False, index=idx)
    if hy is not None:
        hy = hy.reindex(idx)
        stress |= (hy - hy.shift(20)) > config.VETO_HY_RISE
        hy_known = (hy - hy.shift(20)).notna()
    if baa is not None:
        baa = baa.reindex(idx)
        stress |= ~hy_known & ((baa - baa.shift(20)) > 0.3)
    return stress


def market_score(d: dict) -> pd.DataFrame:
    """Gesamtscore und Teilscores je Handelstag."""
    idx = d["spx"].index
    angst_p = {k: v.reindex(idx) for k, v in angst_parts(d).items()}
    wende_p = {k: v.reindex(idx) for k, v in wende_parts(d).items()}
    makro_p = {k: v.reindex(idx) for k, v in makro_parts(d).items()}

    out = pd.DataFrame(index=idx)
    out["angst"] = weighted_mean(angst_p, ANGST_WEIGHTS)
    out["wende"] = weighted_mean(wende_p, WENDE_WEIGHTS)
    out["makro"] = weighted_mean(makro_p, MAKRO_WEIGHTS) if makro_p else np.nan

    w = config.WEIGHTS
    sub = out[["angst", "wende", "makro"]]
    weights = pd.Series(w)
    out["score"] = (sub.fillna(0) * weights).sum(axis=1) / (sub.notna() * weights).sum(axis=1)

    veto = pd.Series(False, index=idx)
    if d.get("sahm") is not None:
        veto = (d["sahm"].reindex(idx) >= config.VETO_SAHM) & credit_stress(d, idx)
    out["veto"] = veto
    out["trend_ok"] = d["spx"] >= d["spx"].rolling(200).mean()
    out.loc[veto, "score"] = out.loc[veto, "score"].clip(upper=config.VETO_CAP)

    for name, parts in (("angst", angst_p), ("wende", wende_p), ("makro", makro_p)):
        for k, v in parts.items():
            out[f"{name}.{k}"] = v
    return out


def signal(score: float, trend_ok: bool = True) -> dict:
    if score is None or np.isnan(score):
        return {"color": "grey", "label": "Keine Daten", "lever": "-"}
    if score >= config.GREEN_FROM:
        if trend_ok or not config.TREND_FILTER:
            return {"color": "green", "label": "Dip kaufen", "lever": "2x, mit viel Risikobereitschaft 3x"}
        return {"color": "yellow", "label": "Dip im Abwärtstrend", "lever": "kein Hebel, bis der S&P 500 wieder über der 200-Tage-Linie liegt"}
    if score >= config.RED_BELOW:
        return {"color": "yellow", "label": "Leichter Rücksetzer", "lever": "beobachten, noch kein Hebel-Neukauf"}
    return {"color": "red", "label": "Kein Dip", "lever": "abwarten"}


def exit_signal(close: pd.Series) -> dict:
    """Hebel nur über der 200-Tage-Linie halten (Gayed, 'Leverage for the Long Run')."""
    close = close.dropna()
    sma200 = close.rolling(200).mean()
    if sma200.dropna().empty:
        return {"hold": None}
    above = close > sma200
    last = bool(above.iloc[-1])
    changed = above.ne(above.shift())
    since = int(len(above) - 1 - np.flatnonzero(changed.to_numpy())[-1])
    return {
        "hold": last,
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
