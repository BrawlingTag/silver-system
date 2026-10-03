"""Holt die Daten, prüft die Kauf- und Verkaufsregeln und schreibt site/data.json.

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
    tickers = list(config.INDEXES) + [config.VIX]
    px = src.closes(tickers, start=config.HISTORY_START)
    spx = px["^GSPC"].dropna()
    idx = spx.index

    def col(t):
        s = px[t].dropna() if t in px else None
        return s.reindex(idx).ffill() if s is not None and len(s) else None

    fg = src.fear_greed(days=800)
    return {
        "spx": spx,
        "ndx": col("^NDX"),
        "world": col("URTH"),
        "vix": col(config.VIX),
        "fear_greed": fg.sort_index() if fg is not None else None,
    }


def last_value(s):
    return None if s is None or s.dropna().empty else round(float(s.dropna().iloc[-1]), 1)


def mood(fear_greed) -> str:
    """Ein Satz zur Stimmung, nur als Info neben den Regeln."""
    if fear_greed is None:
        return ""
    if fear_greed < 25:
        return "Extreme Angst"
    if fear_greed < 45:
        return "Angst"
    if fear_greed <= 55:
        return "Neutral"
    if fear_greed <= 75:
        return "Gier"
    return "Extreme Gier"


def rule_rows(row) -> list:
    pct = lambda v: f"{v:+.1f} %".replace(".", ",")  # noqa: E731
    return [
        {
            "label": f"Rücksetzer: Nasdaq 100 mindestens {config.DIP_PCT:g} % unter dem Hoch",
            "value": f"heute {pct(-row['drawdown'])}, tiefster Stand der letzten {config.DIP_WINDOW} Tage {pct(-row['drawdown_max'])}",
            "ok": bool(row["dip"]),
        },
        {
            "label": "Aufwärtstrend: Nasdaq 100 über der 200-Tage-Linie",
            "value": f"{pct(row['distance'])} zur Linie",
            "ok": bool(row["trend"]),
        },
        {
            "label": f"Dip dreht: RSI kreuzt über seinen {config.RSI_MA}-Tage-Schnitt",
            "value": f"RSI {row['rsi']:.0f}, Schnitt {row['rsi_ma']:.0f}"
                     + (f", gekreuzt in den letzten {config.SIGNAL_HOLD} Tagen" if row["turn_recent"] else ""),
            "ok": bool(row["turn_recent"]),
        },
    ]


def build(src, out_path: Path) -> dict:
    d = gather_market(src)
    rl = ind.rules(d["ndx"])
    last = rl.iloc[-1]
    asof = last.name

    exits = []
    for t, name in config.INDEXES.items():
        s = d["spx"] if t == "^GSPC" else (d["ndx"] if t == "^NDX" else d["world"])
        if s is not None:
            exits.append({"name": name, **ind.exit_signal(s)})

    hist = rl.loc[config.HISTORY_FROM:]
    history = {
        "dates": [x.strftime("%Y-%m-%d") for x in hist.index],
        "ndx": [clean(round(float(v), 1)) for v in hist["close"]],
        "sma200": [clean(round(float(v), 1)) for v in hist["sma200"]],
        "buys": [x.strftime("%Y-%m-%d") for x in hist.index[hist["buy"]]],
        "sells": [x.strftime("%Y-%m-%d") for x in hist.index[hist["sell"]]],
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

    fg, vix = last_value(d["fear_greed"]), last_value(d["vix"])
    data = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": asof.strftime("%Y-%m-%d"),
        "signal": ind.status(last),
        "rules": rule_rows(last),
        "info": {"fear_greed": fg, "mood": mood(fg), "vix": vix},
        "exit_below": config.EXIT_BELOW,
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
    log.info("%s (%s) am %s, %d Aktien -> %s",
             data["signal"]["label"], data["signal"]["color"], data["asof"], len(data["stocks"]), out)


if __name__ == "__main__":
    main()
