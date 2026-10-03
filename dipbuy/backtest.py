"""Backtest: die Kauf- und Verkaufsregeln rückwirkend ab 2007 prüfen.

Aufruf: python -m dipbuy.backtest [ausgabedatei.json]
"""

import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd

from . import build, config, strategy
from . import indicators as ind

log = logging.getLogger("dipbuy")

EVAL_FROM = config.HISTORY_FROM
NEW_SIGNAL_AFTER = 20  # Kaufsignale innerhalb von 20 Handelstagen zählen als ein Dip
HORIZONS = {"3M": 63, "12M": 252}
DIP_PCTS = [4, 6, 8, 10]
RSI_MAS = [3, 5, 8]


def leveraged(close: pd.Series, lever: int) -> pd.Series:
    """Täglich gehebelter Index inklusive grober laufender Kosten."""
    return (1 + strategy.daily_returns(close, lever)).cumprod()


def fwd(series: pd.Series, day, n: int):
    i = series.index.get_loc(day)
    if i + n >= len(series):
        return None
    return float(series.iloc[i + n] / series.iloc[i] - 1) * 100


def first_signals(buy: pd.Series) -> list:
    """Erster Kauftag je Dip: weitere Signale innerhalb von NEW_SIGNAL_AFTER Tagen zählen nicht neu."""
    days, last = [], None
    for i, flag in enumerate(buy.to_numpy()):
        if flag and (last is None or i - last > NEW_SIGNAL_AFTER):
            days.append(buy.index[i])
        if flag:
            last = i
    return days


def signal_rows(ndx: pd.Series, rl: pd.DataFrame) -> list:
    x3 = leveraged(ndx, 3)
    rows = []
    for day in first_signals(rl["buy"].loc[EVAL_FROM:]):
        i = ndx.index.get_loc(day)
        after = ndx.iloc[i: i + 64]
        row = {
            "date": day.strftime("%Y-%m-%d"),
            "drawdown": round(float(rl.loc[day, "drawdown_max"]), 1),
            "further_drop": round(float((after.min() / ndx.iloc[i] - 1) * 100), 1),
        }
        for h, n in HORIZONS.items():
            row[f"ndx_{h}"] = fwd(ndx, day, n)
            row[f"ndx3x_{h}"] = fwd(x3, day, n)
        rows.append(row)
    return rows


def summarize(rows: list, years: float) -> dict:
    if not rows:
        return {"count": 0}
    df = pd.DataFrame(rows)
    dates = pd.to_datetime(df["date"])
    out = {
        "count": len(df),
        "per_year": round(len(df) / years, 1),
        "gap_median_days": int(dates.diff().dt.days.median()) if len(df) > 1 else None,
        "further_drop_avg": round(float(df["further_drop"].mean()), 1),
        "further_drop_worst": round(float(df["further_drop"].min()), 1),
    }
    for col in ("ndx_3M", "ndx3x_3M", "ndx3x_12M"):
        v = df[col].dropna()
        out[col] = round(float(v.mean()), 1) if len(v) else None
        out[col + "_pos"] = round(float((v > 0).mean() * 100)) if len(v) else None
    return out


def baseline(ndx: pd.Series) -> dict:
    """Durchschnittsrendite, wenn man an einem beliebigen Tag kauft (zum Vergleich)."""
    out = {}
    for k, s in {"ndx": ndx, "ndx3x": leveraged(ndx, 3)}.items():
        s = s.loc[EVAL_FROM:]
        for h, n in HORIZONS.items():
            r = (s.shift(-n) / s - 1).dropna() * 100
            out[f"{k}_{h}"] = round(float(r.mean()), 1)
            out[f"{k}_{h}_pos"] = round(float((r > 0).mean() * 100))
    return out


def sensitivity(d: dict, years: float) -> list:
    """Wie ändern sich Signale und Strategie, wenn man die Regeln etwas anders einstellt?"""
    ndx = d["ndx"].dropna()
    rows = []
    for dip in DIP_PCTS:
        for ma in RSI_MAS:
            rl = ind.rules(ndx, dip_pct=dip, rsi_ma=ma)
            s = summarize(signal_rows(ndx, rl), years)
            sim = strategy.simulate(ndx, 3, rl["buy"] | rl["reentry"], rl["below"], EVAL_FROM)
            rows.append({"dip_pct": dip, "rsi_ma": ma, **s, "cagr": sim["cagr"], "max_dd": sim["max_dd"]})
    return rows


def fmt(v, suffix=""):
    return "–" if v is None else f"{v:+.1f}{suffix}"


def report(result: dict) -> str:
    s, b = result["summary"], result["baseline"]
    lines = [
        f"# Backtest Kauf- und Verkaufsregeln ({result['from']} bis {result['to']})",
        "",
        f"Kauf: Nasdaq 100 mindestens {config.DIP_PCT:g} % unter dem Hoch (in den letzten {config.DIP_WINDOW} Tagen), "
        f"über der 200-Tage-Linie, RSI kreuzt über seinen {config.RSI_MA}-Tage-Schnitt. "
        f"Verkauf: mehr als {config.EXIT_BELOW:g} % unter der 200-Tage-Linie. "
        "Wiedereinstieg: nach einem Verkauf wieder über der 200-Tage-Linie.",
        "",
        "## Dip-Kaufsignale",
        "",
        f"{s['count']} Signale, {s.get('per_year')} pro Jahr, Abstand im Median {s.get('gap_median_days') or '–'} Tage. "
        f"Nach dem Signal fiel der Nasdaq im Schnitt noch {s.get('further_drop_avg')} %, schlimmstenfalls {s.get('further_drop_worst')} %.",
        "",
        "| | nach Signal | an beliebigem Tag |",
        "| --- | --- | --- |",
        f"| Nasdaq 100, 3 Monate | {fmt(s.get('ndx_3M'), ' %')} ({s.get('ndx_3M_pos')} % pos.) | {fmt(b['ndx_3M'], ' %')} ({b['ndx_3M_pos']} % pos.) |",
        f"| Nasdaq 3x, 3 Monate | {fmt(s.get('ndx3x_3M'), ' %')} ({s.get('ndx3x_3M_pos')} % pos.) | {fmt(b['ndx3x_3M'], ' %')} ({b['ndx3x_3M_pos']} % pos.) |",
        f"| Nasdaq 3x, 12 Monate | {fmt(s.get('ndx3x_12M'), ' %')} ({s.get('ndx3x_12M_pos')} % pos.) | {fmt(b['ndx3x_12M'], ' %')} ({b['ndx3x_12M_pos']} % pos.) |",
        "",
    ]
    lines += strategy.report(result["strategies"])
    lines += [
        "## Andere Einstellungen (Nasdaq 3x, Regeln)",
        "",
        "| Rücksetzer ab | RSI-Schnitt | Signale pro Jahr | Nasdaq 3x 3M | danach noch schlimmstens | Rendite p.a. | Max. Rückgang |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in result["sensitivity"]:
        lines.append(f"| {r['dip_pct']} % | {r['rsi_ma']} Tage | {r.get('per_year', 0)} | {fmt(r.get('ndx3x_3M'), ' %')} "
                     f"| {r.get('further_drop_worst', '–')} % | {r['cagr']:+.1f} % | {r['max_dd']:.1f} % |")
    lines += ["", "## Alle Kaufsignale", "", "| Datum | Rücksetzer | danach noch | Nasdaq 3M | Nasdaq 3x 3M | Nasdaq 3x 12M |",
              "| --- | --- | --- | --- | --- | --- |"]
    for r in result["signals"]:
        lines.append(f"| {r['date']} | -{r['drawdown']} % | {r['further_drop']} % | {fmt(r['ndx_3M'], ' %')} "
                     f"| {fmt(r['ndx3x_3M'], ' %')} | {fmt(r['ndx3x_12M'], ' %')} |")
    return "\n".join(lines)


def run(src) -> dict:
    d = build.gather_market(src)
    ndx = d["ndx"].dropna()
    rl = ind.rules(ndx)
    span = ndx.loc[EVAL_FROM:].index
    years = (span[-1] - span[0]).days / 365.25
    rows = signal_rows(ndx, rl)
    strat = strategy.strategies(d, rl, EVAL_FROM)
    return {
        "from": span[0].strftime("%Y-%m-%d"),
        "to": span[-1].strftime("%Y-%m-%d"),
        "signals": rows,
        "summary": summarize(rows, years),
        "baseline": baseline(ndx),
        "strategies": {k: {kk: vv for kk, vv in v.items() if kk != "equity"} for k, v in strat.items()},
        "sensitivity": sensitivity(d, years),
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
