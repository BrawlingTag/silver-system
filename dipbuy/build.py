"""Holt die Daten, berechnet Score, Kauf- und Verkaufssignal und schreibt site/data.json.

Aufruf: python -m dipbuy.build [ausgabedatei]
"""

import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
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

    fg = src.fear_greed(days=2500)  # so weit zurück wie CNN es hergibt, sonst 800 Tage
    return {
        "spx": spx,
        "ndx": col("^NDX"),
        "world": col("URTH"),
        "acwi": col("ACWI"),
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


def rule_rows(sig) -> list:
    pct = lambda v: f"{v:.1f} %".replace(".", ",")  # noqa: E731
    num = lambda v: "–" if pd.isna(v) else f"{v:.1f}".replace(".", ",")  # noqa: E731
    w = config.SETUP_WINDOW
    note = lambda ok, now: "" if now or not ok else f", erfüllt in den letzten {w} Tagen"  # noqa: E731
    fg = sig["fear_greed"]
    return [
        {
            "label": f"S&P 500 mindestens {config.ATH_PCT:g} % unter dem Allzeithoch",
            "value": f"heute {pct(sig['drawdown'])} darunter" + note(sig["c_drawdown"], sig["drawdown"] >= config.ATH_PCT),
            "ok": bool(sig["c_drawdown"]),
        },
        {
            "label": f"VIX über {config.VIX_MIN:g}",
            "value": f"heute {num(sig['vix'])}" + note(sig["c_vix"], sig["vix"] > config.VIX_MIN),
            "ok": bool(sig["c_vix"]),
        },
        {
            "label": f"CNN Fear & Greed unter {config.FG_MAX:g}",
            "value": ("kein Wert, zählt als erfüllt" if pd.isna(fg)
                      else f"heute {fg:.0f} ({mood(fg)})" + note(sig["c_fear_greed"], fg < config.FG_MAX)),
            "ok": bool(sig["c_fear_greed"]),
        },
        {
            "label": f"Dann kaufen: RSI über dem Schnitt der letzten {config.RSI_MA} Tage",
            "value": f"RSI {sig['rsi']:.0f}, Schnitt {sig['rsi_ma']:.0f}",
            "ok": bool(sig["turn"]),
        },
    ]


def score_parts(sig) -> list:
    names = {"drawdown": "S&P unter Hoch", "vix": "VIX", "fear_greed": "CNN"}
    return [{"name": n, "points": None if pd.isna(sig["score_" + k]) else round(float(sig["score_" + k]))}
            for k, n in names.items()]


def sell_info(pos) -> dict:
    """Stand des Verkaufssignals für die Seite."""
    last = pos.iloc[-1]
    fg = last["fear_greed"]
    greed_days = pos.index[pos["greed_start"]]
    sells = pos.index[pos["sell"]]
    hold = ~pos["out"]
    changed = np.flatnonzero(hold.ne(hold.shift()).to_numpy())
    return {
        "threshold": config.SELL_FG,
        "delay": config.SELL_DELAY,
        "fear_greed": None if pd.isna(fg) else round(float(fg)),
        "mood": "" if pd.isna(fg) else mood(float(fg)),
        "hold": bool(hold.iloc[-1]),
        "days": int(len(hold) - 1 - changed[-1]) if len(changed) else None,
        "last_greed": greed_days[-1].strftime("%Y-%m-%d") if len(greed_days) else None,
        "last_sell": sells[-1].strftime("%Y-%m-%d") if len(sells) else None,
    }


def build(src, out_path: Path) -> dict:
    d = gather_market(src)
    sig = ind.signals(d["spx"], d["vix"], d["fear_greed"])
    pos = ind.greed_exit(sig)
    last_sig, last_pos = sig.iloc[-1], pos.iloc[-1]
    asof = sig.index[-1]

    hist = sig.loc[config.HISTORY_FROM:].index
    hpos = pos.reindex(hist)
    keys = {"^NDX": "ndx", "^GSPC": "spx", "URTH": "world", "ACWI": "acwi"}
    order = ["^NDX", "^GSPC", "URTH", "ACWI"]
    rnd = lambda s: [None if pd.isna(v) else round(float(v), 2) for v in s]  # noqa: E731
    indexes = []
    for t in order:
        s = d.get(keys[t])
        if s is None or s.dropna().empty:
            continue
        s = s.reindex(sig.index)
        indexes.append({"name": config.INDEXES[t], "close": rnd(s.reindex(hist)),
                        "sma200": rnd(s.rolling(200).mean().reindex(hist))})
    history = {
        "dates": [x.strftime("%Y-%m-%d") for x in hist],
        "indexes": indexes,
        "score": [None if pd.isna(v) else int(round(v)) for v in sig["score"].reindex(hist)],
        "buys": [x.strftime("%Y-%m-%d") for x in hist[sig["buy_start"].reindex(hist).to_numpy()]],
        "sells": [x.strftime("%Y-%m-%d") for x in hist[hpos["sell"].to_numpy()]],
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
        "signal": ind.status(last_sig, last_pos),
        "score": None if pd.isna(last_sig["score"]) else round(float(last_sig["score"])),
        "score_parts": score_parts(last_sig),
        "rules": rule_rows(last_sig),
        "info": {"fear_greed": fg, "mood": mood(fg), "vix": vix},
        "sell": sell_info(pos),
        "history": history,
        "stocks": stocks,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(clean(data), ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return data


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from . import fetch

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("site/data.json")
    data = build(fetch, out)
    log.info("%s (%s), Score %s am %s, %d Aktien -> %s", data["signal"]["label"], data["signal"]["color"],
             data["score"], data["asof"], len(data["stocks"]), out)


if __name__ == "__main__":
    main()
