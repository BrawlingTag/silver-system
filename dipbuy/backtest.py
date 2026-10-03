"""Backtest: Score rückwirkend berechnen und jedes Kaufsignal auswerten.

Aufruf: python -m dipbuy.backtest [ausgabedatei.json]
"""

import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import build, config, strategy
from . import indicators as ind

log = logging.getLogger("dipbuy")

EVAL_FROM = config.HISTORY_FROM
NEW_EPISODE_AFTER = 20  # Handelstage ohne Signal, bevor ein neues Signal zählt
THRESHOLDS = [45, 50, 55, 60]
RSI_MAS = [3, 5, 8]
DETAIL_THRESHOLD = config.GREEN_FROM  # nur für diese Schwelle werden alle Einzelsignale ausgegeben


def trend_filters(spx: pd.Series) -> dict:
    """Varianten, die Kaufsignale in Bärenmärkten ausfiltern sollen."""
    sma200 = spx.rolling(200).mean()
    above = spx >= sma200
    return {
        "ohne Filter": pd.Series(True, index=spx.index),
        "über 200-Tage-Linie": above,
    }
HORIZONS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}
# Grobe jährliche Kosten gehebelter ETFs (Gebühr plus Finanzierung)
LEVER_COST = {2: 0.015, 3: 0.03}


def leveraged(close: pd.Series, lever: int) -> pd.Series:
    """Täglich gehebelter Index inklusive grober laufender Kosten."""
    r = close.pct_change().fillna(0)
    daily = lever * r - LEVER_COST[lever] / 252
    return (1 + daily).cumprod()


def episodes(score: pd.Series, threshold: float) -> list:
    """Erster Tag jeder Grün-Phase; nach NEW_EPISODE_AFTER Tagen ohne Grün beginnt eine neue."""
    on = score >= threshold
    out, last_on = [], None
    for i, (day, flag) in enumerate(on.items()):
        if not flag:
            continue
        if last_on is None or i - last_on > NEW_EPISODE_AFTER:
            out.append(day)
        last_on = i
    return out


def fwd(series: pd.Series, day, n: int):
    i = series.index.get_loc(day)
    if i + n >= len(series):
        return None
    return float(series.iloc[i + n] / series.iloc[i] - 1) * 100


def analyse(d: dict, sc: pd.DataFrame, threshold: float, allowed: pd.Series | None = None,
            entries: pd.Series | None = None) -> list:
    spx, ndx = d["spx"], d["ndx"]
    lev = {"ndx2x": leveraged(ndx, 2), "ndx3x": leveraged(ndx, 3), "spx2x": leveraged(spx, 2)}
    peak = spx.cummax()
    rows = []
    if entries is not None:
        score, threshold = entries.astype(float) * 100, 50
    else:
        score = sc["score"] if allowed is None else sc["score"].where(allowed.reindex(sc.index, fill_value=False), 0)
    for day in episodes(score, threshold):
        i = spx.index.get_loc(day)
        # Letztes Hoch vor dem Signal (Beginn des Rücksetzers)
        before = spx.iloc[: i + 1]
        peak_day = before[before == peak.iloc[i]].index[-1]
        recent = before.iloc[-252:]
        local_peak_day = recent.idxmax()
        # Tiefpunkt dieses Rücksetzers: tiefster Schluss zwischen Hoch und 6 Monate nach Signal
        window = spx.loc[local_peak_day: spx.index[min(i + 126, len(spx) - 1)]]
        bottom_day = window.idxmin()
        row = {
            "date": day.strftime("%Y-%m-%d"),
            "score": round(float(sc.loc[day, "score"]), 1),
            "angst": round(float(sc.loc[day, "angst"]), 1),
            "wende": round(float(sc.loc[day, "wende"]), 1),
            "dd_at_signal": round(float((1 - spx.iloc[i] / recent.max()) * 100), 1),
            "peak_date": local_peak_day.strftime("%Y-%m-%d"),
            "days_peak_to_signal": int((day - local_peak_day).days),
            "bottom_date": bottom_day.strftime("%Y-%m-%d"),
            "days_bottom_to_signal": int((day - bottom_day).days),
            "further_drop": round(float((window.loc[day:].min() / spx.iloc[i] - 1) * 100), 1),
            "below_ath": round(float((1 - spx.iloc[i] / peak.loc[peak_day]) * 100), 1),
        }
        for h, n in HORIZONS.items():
            row[f"spx_{h}"] = fwd(spx, day, n)
            row[f"ndx_{h}"] = fwd(ndx, day, n)
            for k, s in lev.items():
                row[f"{k}_{h}"] = fwd(s, day, n)
        rows.append(row)
    return rows


def baseline(d: dict, start) -> dict:
    """Durchschnittsrendite, wenn man an einem beliebigen Tag kauft (zum Vergleich)."""
    out = {}
    series = {"spx": d["spx"], "ndx": d["ndx"], "ndx2x": leveraged(d["ndx"], 2), "ndx3x": leveraged(d["ndx"], 3)}
    for k, s in series.items():
        s = s.loc[start:]
        for h, n in HORIZONS.items():
            r = (s.shift(-n) / s - 1).dropna() * 100
            out[f"{k}_{h}"] = round(float(r.mean()), 1)
            out[f"{k}_{h}_pos"] = round(float((r > 0).mean() * 100), 0)
    return out


def summarize(rows: list) -> dict:
    if not rows:
        return {"count": 0}
    df = pd.DataFrame(rows)
    dates = pd.to_datetime(df["date"])
    gaps = dates.diff().dt.days.dropna()
    s = {
        "count": len(df),
        "avg_days_between": round(float(gaps.mean()), 0) if len(gaps) else None,
        "median_days_between": round(float(gaps.median()), 0) if len(gaps) else None,
        "avg_days_peak_to_signal": round(float(df["days_peak_to_signal"].mean()), 0),
        "median_days_peak_to_signal": round(float(df["days_peak_to_signal"].median()), 0),
        "avg_days_bottom_to_signal": round(float(df["days_bottom_to_signal"].mean()), 0),
        "share_after_bottom": round(float((df["days_bottom_to_signal"] >= 0).mean() * 100), 0),
        "avg_dd_at_signal": round(float(df["dd_at_signal"].mean()), 1),
        "avg_further_drop": round(float(df["further_drop"].mean()), 1),
        "worst_further_drop": round(float(df["further_drop"].min()), 1),
    }
    for col in [c for c in df.columns if c.endswith(tuple(HORIZONS))]:
        v = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(v):
            s[col] = round(float(v.mean()), 1)
            s[f"{col}_pos"] = round(float((v > 0).mean() * 100), 0)
    return s


def fmt(v, suffix=""):
    return "–" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:+.1f}{suffix}" if isinstance(v, float) else f"{v}{suffix}"


def report(result: dict) -> str:
    lines = [f"# Backtest Dip-Buy-Score ({result['from']} bis {result['to']})", ""]
    lines.append("Datenverfügbarkeit: " + ", ".join(f"{k} ab {v}" for k, v in result["coverage"].items()))
    lines.append("")
    lines += strategy.report(result["strategies"])
    years = (pd.Timestamp(result["to"]) - pd.Timestamp(result["from"])).days / 365.25
    lines += [
        "## Vergleich der Schwellen",
        "",
        "| Filter | Einstieg | Schwelle | Signale | pro Jahr | Abstand Median (Tage) | Hoch bis Signal Median (Tage) | nach dem Tief | danach noch Schnitt / schlimmstens | S&P 3M | Nasdaq 3x 3M | Nasdaq 3x 12M |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for block in result["signals"].values():
        s = block["summary"]
        if not s["count"]:
            lines.append(f"| {block['filter']} | {block['entry']} | {block['threshold']} | 0 | | | | | | | | |")
            continue
        lines.append(
            f"| {block['filter']} | {block['entry']} | {block['threshold']} | {s['count']} | {s['count'] / years:.1f} | {s['median_days_between']} | {s['median_days_peak_to_signal']} "
            f"| {s['share_after_bottom']:.0f} % | {s['avg_further_drop']} % / {s['worst_further_drop']} % "
            f"| {fmt(s.get('spx_3M'), ' %')} ({s.get('spx_3M_pos')} % pos.) | {fmt(s.get('ndx3x_3M'), ' %')} ({s.get('ndx3x_3M_pos')} % pos.) "
            f"| {fmt(s.get('ndx3x_12M'), ' %')} ({s.get('ndx3x_12M_pos')} % pos.) |"
        )
    lines.append("")
    for name, block in result["signals"].items():
        if (block["threshold"], block["filter"], block["entry"]) != (DETAIL_THRESHOLD, "über 200-Tage-Linie", f"RSI über MA{config.RSI_MA}"):
            continue
        s = block["summary"]
        lines.append(f"## Signal: Score ab {block['threshold']} ({name})")
        lines.append("")
        lines.append(f"Anzahl Signale: {s['count']}")
        if not s["count"]:
            continue
        lines += [
            f"Abstand zwischen Signalen: Schnitt {s['avg_days_between']} Tage, Median {s['median_days_between']} Tage",
            f"Vom Hoch bis zum Signal: Schnitt {s['avg_days_peak_to_signal']} Tage, Median {s['median_days_peak_to_signal']} Tage",
            f"Signal relativ zum Tiefpunkt: Schnitt {s['avg_days_bottom_to_signal']} Tage, {s['share_after_bottom']} % nach dem Tief",
            f"Rücksetzer beim Signal: Schnitt {s['avg_dd_at_signal']} %, danach noch Schnitt {s['avg_further_drop']} % / schlimmstens {s['worst_further_drop']} %",
            "",
            "| Horizont | S&P 500 | Nasdaq 100 | Nasdaq 2x | Nasdaq 3x | S&P 2x |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for h in HORIZONS:
            cells = [f"{fmt(s.get(f'{k}_{h}'), ' %')} ({s.get(f'{k}_{h}_pos', '–')} % pos.)" for k in ("spx", "ndx", "ndx2x", "ndx3x", "spx2x")]
            lines.append(f"| {h} | " + " | ".join(cells) + " |")
        lines.append("")
        lines.append("| Datum | Score | Rücksetzer | Tage seit Hoch | Tage nach Tief | danach noch | S&P 12M | Nasdaq 3x 12M |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in block["rows"]:
            lines.append(f"| {r['date']} | {r['score']} | -{r['dd_at_signal']} % | {r['days_peak_to_signal']} | {r['days_bottom_to_signal']} | {r['further_drop']} % | {fmt(r['spx_12M'], ' %')} | {fmt(r['ndx3x_12M'], ' %')} |")
        lines.append("")
    b = result["baseline"]
    lines.append("## Zum Vergleich: Kauf an einem beliebigen Tag")
    lines.append("")
    lines.append("| Horizont | S&P 500 | Nasdaq 100 | Nasdaq 2x | Nasdaq 3x |")
    lines.append("| --- | --- | --- | --- | --- |")
    for h in HORIZONS:
        lines.append(f"| {h} | " + " | ".join(f"{b[f'{k}_{h}']:+.1f} % ({b[f'{k}_{h}_pos']:.0f} % pos.)" for k in ("spx", "ndx", "ndx2x", "ndx3x")) + " |")
    return "\n".join(lines)


def run(src) -> dict:
    d = build.gather_market(src)
    sc = ind.market_score(d)
    sc = sc.loc[EVAL_FROM:].dropna(subset=["score"])
    coverage = {k: v.dropna().index.min().strftime("%Y-%m-%d") for k, v in d.items() if v is not None and not v.dropna().empty}
    signals = {}
    for fname, allowed in trend_filters(d["spx"]).items():
        allowed = allowed.reindex(sc.index, fill_value=False)
        for thr in THRESHOLDS:
            rows = analyse(d, sc, thr, allowed)
            signals[f"ab {thr}, {fname}, sofort"] = {
                "threshold": thr, "filter": fname, "entry": "sofort", "rows": rows, "summary": summarize(rows)}
            for ma in RSI_MAS:
                _, trigger = ind.dip_entry(sc["score"], allowed, sc["rsi"], ma=ma, green=thr)
                rows = analyse(d, sc, thr, entries=trigger)
                signals[f"ab {thr}, {fname}, RSI über MA{ma}"] = {
                    "threshold": thr, "filter": fname, "entry": f"RSI über MA{ma}", "rows": rows, "summary": summarize(rows)}
    strat = strategy.strategies(d, sc, EVAL_FROM)
    return {
        "strategies": {k: {kk: vv for kk, vv in v.items() if kk != "equity"} for k, v in strat.items()},
        "from": sc.index.min().strftime("%Y-%m-%d"),
        "to": sc.index.max().strftime("%Y-%m-%d"),
        "coverage": coverage,
        "signals": signals,
        "baseline": baseline(d, EVAL_FROM),
        "daily": {
            "dates": [x.strftime("%Y-%m-%d") for x in sc.index],
            "score": [round(float(v), 1) for v in sc["score"]],
            "spx": [round(float(v), 1) for v in d["spx"].reindex(sc.index)],
        },
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from . import fetch

    result = run(fetch)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("backtest.json")
    out.write_text(json.dumps(build.clean(result), ensure_ascii=False, allow_nan=False))
    text = report(result)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
