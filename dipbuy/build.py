"""Holt alle Daten, rechnet die Scores und schreibt site/data.json.

Aufruf: python -m dipbuy.build [ausgabedatei]
"""

import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config
from . import indicators as ind

log = logging.getLogger("dipbuy")

PART_LABELS = {
    "angst.fear_greed": ("CNN Fear & Greed", "fear_greed", "{:.0f}"),
    "angst.vix": ("VIX", "vix", "{:.1f}"),
    "angst.vix_term": ("VIX / VIX3M (über 1 = Panik)", "vix_term", "{:.2f}"),
    "angst.dd_spx": ("S&P 500 unter Hoch", "dd_spx", "-{:.1f} %"),
    "angst.dd_ndx": ("Nasdaq 100 unter Hoch", "dd_ndx", "-{:.1f} %"),
    "angst.dd_world": ("MSCI World unter Hoch", "dd_world", "-{:.1f} %"),
    "angst.breadth": ("S&P-500-Aktien über 200-Tage-Linie", "breadth", "{:.0f} %"),
    "wende.rsi_turn": ("RSI dreht aus überverkauft", None, None),
    "wende.sma20": ("Index zurück über 20-Tage-Linie", None, None),
    "wende.sma50": ("Index zurück über 50-Tage-Linie", None, None),
    "wende.vix_falling": ("VIX fällt vom Hoch", None, None),
    "makro.hy_level": ("High-Yield-Spread", "hy_spread", "{:.2f} %"),
    "makro.hy_trend": ("High-Yield-Spread, Änderung 20 Tage", "hy_change", "{:+.2f} Pp."),
    "makro.sahm": ("Sahm-Regel (Rezession ab 0,5)", "sahm", "{:.2f}"),
}


def clean(x):
    """NaN und Unendlich als null ausgeben, damit data.json gültiges JSON bleibt."""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


def gather_market(src) -> dict:
    tickers = list(config.INDEXES) + [config.VIX, config.VIX3M]
    px = src.closes(tickers, period="3y")
    spx = px["^GSPC"].dropna()
    idx = spx.index

    def col(t):
        s = px[t].dropna() if t in px else None
        return s.reindex(idx).ffill() if s is not None and len(s) else None

    def aligned(s):
        if s is None:
            return None
        s = s[~s.index.duplicated(keep="last")].sort_index()
        return s.reindex(s.index.union(idx)).ffill().reindex(idx)

    return {
        "spx": spx,
        "ndx": col("^NDX"),
        "world": col("URTH"),
        "vix": col(config.VIX),
        "vix3m": col(config.VIX3M),
        "fear_greed": aligned(src.fear_greed()),
        "breadth": aligned(src.breadth()),
        "hy_spread": aligned(src.fred("BAMLH0A0HYM2")),
        "sahm": aligned(src.fred("SAHMREALTIME")),
    }


def raw_values(d: dict) -> dict:
    """Rohwerte am letzten Tag, für die Anzeige neben den Teilscores."""
    last = lambda s: None if s is None or s.dropna().empty else float(s.dropna().iloc[-1])  # noqa: E731
    vals = {
        "fear_greed": last(d["fear_greed"]),
        "vix": last(d["vix"]),
        "vix_term": last(d["vix"] / d["vix3m"]) if d["vix3m"] is not None else None,
        "dd_spx": last(ind.drawdown(d["spx"])),
        "dd_ndx": last(ind.drawdown(d["ndx"])),
        "dd_world": last(ind.drawdown(d["world"])) if d["world"] is not None else None,
        "breadth": last(d["breadth"]),
        "hy_spread": last(d["hy_spread"]),
        "hy_change": last(d["hy_spread"] - d["hy_spread"].shift(20)) if d["hy_spread"] is not None else None,
        "sahm": last(d["sahm"]),
    }
    return vals


def summary_text(row, dip: bool) -> str:
    angst, wende, makro = row["angst"], row["wende"], row["makro"]
    if row["veto"]:
        return "Rezessionssignal und steigende Kreditspreads: Vorsicht, Score ist auf Gelb gedeckelt."
    if angst < 30:
        a = "Kaum Angst im Markt"
    elif angst < 60:
        a = "Erhöhte Angst"
    else:
        a = "Hohe Angst, Ausverkaufsstimmung"
    if not dip:
        w = "kein nennenswerter Rücksetzer"
    elif wende < 35:
        w = "Wende noch nicht bestätigt"
    elif wende < 65:
        w = "erste Stabilisierung"
    else:
        w = "Wende bestätigt"
    m = "" if makro is None or math.isnan(makro) or makro >= 50 else ", Makro-Lage angespannt"
    return f"{a}, {w}{m}."


def build(src, out_path: Path) -> dict:
    d = gather_market(src)
    sc = ind.market_score(d)
    last = sc.dropna(subset=["score"]).iloc[-1]
    asof = last.name
    dip = bool(ind.dip_present(d["spx"]).loc[asof])
    raw = raw_values(d)

    parts = {"angst": [], "wende": [], "makro": []}
    for key, (label, raw_key, fmt) in PART_LABELS.items():
        if key not in sc.columns or pd.isna(last.get(key)):
            continue
        rv = raw.get(raw_key) if raw_key else None
        parts[key.split(".")[0]].append({
            "label": label,
            "score": round(float(last[key])),
            "value": fmt.format(rv) if (fmt and rv is not None) else None,
        })

    exits = []
    for t, name in config.INDEXES.items():
        s = d["spx"] if t == "^GSPC" else (d["ndx"] if t == "^NDX" else d["world"])
        if s is not None:
            exits.append({"name": name, **ind.exit_signal(s)})

    hist = sc.dropna(subset=["score"]).tail(config.HISTORY_DAYS)
    history = {
        "dates": [x.strftime("%Y-%m-%d") for x in hist.index],
        "score": [round(float(v), 1) for v in hist["score"]],
        "spx": [clean(round(float(v), 2)) for v in d["spx"].reindex(hist.index)],
    }

    stocks = []
    try:
        px = src.closes(config.WATCHLIST, period="2y")
    except Exception as e:  # noqa: BLE001
        log.warning("Watchlist-Kurse nicht abrufbar: %s", e)
        px = pd.DataFrame()
    for t in config.WATCHLIST:
        if t not in px or px[t].dropna().shape[0] < 60:
            continue
        info = src.analyst_info(t)
        row = ind.stock_score(px[t], info)
        stocks.append({"ticker": t, "name": info.get("name", t), **row})
    stocks.sort(key=lambda s: -(s["score"] or -1))

    score = float(last["score"])
    data = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": asof.strftime("%Y-%m-%d"),
        "score": round(score, 1),
        "signal": ind.signal(score),
        "summary": summary_text(last, dip),
        "dip": dip,
        "veto": bool(last["veto"]),
        "sub": {k: clean(round(float(last[k]), 1)) for k in ("angst", "wende", "makro")},
        "weights": config.WEIGHTS,
        "thresholds": {"red_below": config.RED_BELOW, "green_from": config.GREEN_FROM, "strong_from": config.STRONG_FROM},
        "parts": parts,
        "exits": exits,
        "history": history,
        "stocks": stocks,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(clean(data), ensure_ascii=False, indent=1, allow_nan=False))
    return data


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from . import fetch

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("site/data.json")
    data = build(fetch, out)
    log.info("Score %.1f (%s) am %s, %d Aktien -> %s",
             data["score"], data["signal"]["label"], data["asof"], len(data["stocks"]), out)


if __name__ == "__main__":
    main()
