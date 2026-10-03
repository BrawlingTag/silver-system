"""Backtest: Kaufsignal (Panik + RSI dreht) und Verkaufssignal rückwirkend ab 2007 prüfen.

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
ATH_PCTS = [4, 7, 10]
VIX_MINS = [22, 26, 30]


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


def signal_rows(ndx: pd.Series, sig: pd.DataFrame) -> list:
    x3 = leveraged(ndx, 3)
    rows = []
    for day in first_signals(sig["buy"].loc[EVAL_FROM:]):
        i = ndx.index.get_loc(day)
        after = ndx.iloc[i: i + 64]
        row = {
            "date": day.strftime("%Y-%m-%d"),
            "score": round(float(sig.loc[day, "score"])),
            "drawdown": round(float(sig.loc[day, "drawdown"]), 1),
            "vix": round(float(sig.loc[day, "vix"]), 1),
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
    """Wie ändern sich Signale und Strategie, wenn man die Schwellen etwas anders einstellt?"""
    ndx = d["ndx"].dropna()
    rows = []
    for ath in ATH_PCTS:
        for vix in VIX_MINS:
            sig = ind.signals(d["spx"], d["vix"], d["fear_greed"], ath_pct=ath, vix_min=vix)
            pos = ind.greed_exit(sig)
            s = summarize(signal_rows(ndx, sig), years)
            sim = strategy.simulate(ndx, 3, ~pos["out"], pos["sell"], EVAL_FROM)
            rows.append({"ath_pct": ath, "vix_min": vix, **s, "cagr": sim["cagr"], "max_dd": sim["max_dd"]})
    return rows


def score_buckets(rows: list) -> list:
    """Bringt ein höherer Score beim Signal auch mehr Rendite?"""
    if not rows:
        return []
    df = pd.DataFrame(rows)
    out = []
    for lo, hi in ((0, 60), (60, 75), (75, 101)):
        part = df[(df["score"] >= lo) & (df["score"] < hi)]
        v3, v12 = part["ndx3x_3M"].dropna(), part["ndx3x_12M"].dropna()
        out.append({"range": f"{lo}–{min(hi, 100)}", "count": len(part),
                    "ndx3x_3M": round(float(v3.mean()), 1) if len(v3) else None,
                    "ndx3x_12M": round(float(v12.mean()), 1) if len(v12) else None})
    return out


def cnn_check(d: dict) -> dict:
    """Seit es CNN-Werte gibt: wie viele Signale mit und ohne die CNN-Bedingung?"""
    fg = d["fear_greed"]
    if fg is None or fg.dropna().empty:
        return {}
    since = fg.dropna().index[0]
    with_cnn = ind.signals(d["spx"], d["vix"], fg)["buy"].loc[since:]
    without = ind.signals(d["spx"], d["vix"], None)["buy"].loc[since:]
    return {"since": since.strftime("%Y-%m-%d"),
            "with": [x.strftime("%Y-%m-%d") for x in first_signals(with_cnn)],
            "without": [x.strftime("%Y-%m-%d") for x in first_signals(without)]}


def fmt(v, suffix=""):
    return "–" if v is None else f"{v:+.1f}{suffix}"


def report(result: dict) -> str:
    s, b = result["summary"], result["baseline"]
    lines = [
        f"# Backtest Panik-Kaufsignal ({result['from']} bis {result['to']})",
        "",
        f"Kauf: S&P 500 mindestens {config.ATH_PCT:g} % unter dem Allzeithoch, VIX über {config.VIX_MIN:g}, "
        f"CNN Fear & Greed unter {config.FG_MAX:g} (alle in den letzten {config.SETUP_WINDOW} Tagen), "
        f"dann RSI über dem Schnitt der letzten {config.RSI_MA} Tage. "
        "CNN-Werte gibt es nur für die letzten Jahre, davor zählt nur S&P und VIX. "
        f"Verkauf: {config.SELL_DELAY} Handelstage, nachdem CNN Fear & Greed über {config.SELL_FG:g} gestiegen ist; "
        "danach draußen bis zum nächsten Kaufsignal. Ohne CNN-Werte (vor Mitte 2024) gibt es keinen Verkauf.",
        "",
        "## Kaufsignale",
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
        "### Score beim Signal",
        "",
        "| Score | Signale | Nasdaq 3x 3M | Nasdaq 3x 12M |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {r['range']} | {r['count']} | {fmt(r['ndx3x_3M'], ' %')} | {fmt(r['ndx3x_12M'], ' %')} |"
              for r in result["score_buckets"]]
    c = result.get("cnn")
    if c:
        lines += ["", f"Seit {c['since']} (CNN-Werte vorhanden): mit CNN-Bedingung {len(c['with'])} Signale "
                      f"({', '.join(c['with']) or 'keine'}), ohne {len(c['without'])} ({', '.join(c['without']) or 'keine'})."]
    lines.append("")
    lines += strategy.report(result["strategies"], f"Strategie {result['from']} bis {result['to']} "
                             "(vor Mitte 2024 ohne CNN-Werte, also ohne Verkauf)")
    c = result.get("cnn_period")
    if c:
        lines += [f"CNN über {config.SELL_FG:g} seit {c['since']}: "
                  f"{', '.join(c['greed']) or 'nie'}. Verkaufssignale: {', '.join(c['sells']) or 'keine'}.", ""]
        lines += strategy.report(c["strategies"], f"Strategie seit {c['since']} (nur hier gibt es CNN-Werte)")
    lines += [
        "## Andere Schwellen (Nasdaq 3x, Regeln)",
        "",
        "| S&P unter Hoch | VIX über | Signale pro Jahr | Nasdaq 3x 3M | danach noch schlimmstens | Rendite p.a. | Max. Rückgang |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in result["sensitivity"]:
        lines.append(f"| {r['ath_pct']} % | {r['vix_min']} | {r.get('per_year', 0)} | {fmt(r.get('ndx3x_3M'), ' %')} "
                     f"| {r.get('further_drop_worst', '–')} % | {r['cagr']:+.1f} % | {r['max_dd']:.1f} % |")
    lines += ["", "## Alle Kaufsignale", "",
              "| Datum | Score | S&P unter Hoch | VIX | Nasdaq danach noch | Nasdaq 3M | Nasdaq 3x 3M | Nasdaq 3x 12M |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in result["signals"]:
        lines.append(f"| {r['date']} | {r['score']} | -{r['drawdown']} % | {r['vix']} | {r['further_drop']} % | {fmt(r['ndx_3M'], ' %')} "
                     f"| {fmt(r['ndx3x_3M'], ' %')} | {fmt(r['ndx3x_12M'], ' %')} |")
    return "\n".join(lines)


def run(src) -> dict:
    d = build.gather_market(src)
    ndx = d["ndx"].dropna()
    sig = ind.signals(d["spx"], d["vix"], d["fear_greed"])
    span = ndx.loc[EVAL_FROM:].index
    years = (span[-1] - span[0]).days / 365.25
    rows = signal_rows(ndx, sig)
    strat = strategy.strategies(d, sig, EVAL_FROM)
    return {
        "from": span[0].strftime("%Y-%m-%d"),
        "to": span[-1].strftime("%Y-%m-%d"),
        "signals": rows,
        "summary": summarize(rows, years),
        "score_buckets": score_buckets(rows),
        "cnn": cnn_check(d),
        "baseline": baseline(ndx),
        "strategies": {k: {kk: vv for kk, vv in v.items() if kk != "equity"} for k, v in strat.items()},
        "sensitivity": sensitivity(d, years),
        "cnn_period": cnn_period(d, sig),
    }


def cnn_period(d: dict, sig: pd.DataFrame) -> dict:
    """Strategie nur für den Zeitraum, in dem es CNN-Werte (und damit Verkaufssignale) gibt."""
    fg = d["fear_greed"]
    if fg is None or fg.dropna().empty:
        return {}
    since = fg.dropna().index[0]
    pos = ind.greed_exit(sig).loc[since:]
    strat = strategy.strategies(d, sig, since)
    return {
        "since": since.strftime("%Y-%m-%d"),
        "greed": [x.strftime("%Y-%m-%d") for x in pos.index[pos["greed_start"]]],
        "sells": [x.strftime("%Y-%m-%d") for x in pos.index[pos["sell"]]],
        "strategies": {k: {kk: vv for kk, vv in v.items() if kk != "equity"} for k, v in strat.items()},
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
