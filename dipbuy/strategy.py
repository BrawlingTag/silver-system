"""Strategie-Simulation: Kauf beim Dip-Signal, Verkauf beim Ausstiegssignal (Index unter 200-Tage-Linie).

Zwischen Verkauf und nächstem Kauf liegt das Geld unverzinst als Cash. Signale gelten zum Schlusskurs,
gehandelt wird damit ab dem nächsten Tag.
"""

import numpy as np
import pandas as pd

from . import config

LEVER_COST = {1: 0.0, 2: 0.015, 3: 0.03}


def daily_returns(close: pd.Series, lever: int) -> pd.Series:
    return (lever * close.pct_change() - LEVER_COST[lever] / 252).fillna(0)


def simulate(close: pd.Series, lever: int, entries: pd.Series, exits: pd.Series, start) -> dict:
    close = close.loc[start:].dropna()
    rets = daily_returns(close, lever)
    entries = entries.reindex(close.index, fill_value=False)
    exits = exits.reindex(close.index, fill_value=False)

    equity = np.empty(len(close))
    value, invested, trades, entry_day, entry_value = 1.0, False, [], None, None
    for i, day in enumerate(close.index):
        if invested:
            value *= 1 + rets.iloc[i]
        equity[i] = value
        if not invested and entries.iloc[i]:
            invested, entry_day, entry_value = True, day, value
        elif invested and exits.iloc[i]:
            trades.append((entry_day, day, value / entry_value - 1))
            invested = False
    if invested:
        trades.append((entry_day, close.index[-1], value / entry_value - 1))

    eq = pd.Series(equity, index=close.index)
    years = (close.index[-1] - close.index[0]).days / 365.25
    in_market = sum((b - a).days for a, b, _ in trades) / max((close.index[-1] - close.index[0]).days, 1)
    returns = [r for _, _, r in trades]
    return {
        "final": round(float(eq.iloc[-1]), 2),
        "cagr": round(float((eq.iloc[-1] ** (1 / years) - 1) * 100), 1),
        "max_dd": round(float((eq / eq.cummax() - 1).min() * 100), 1),
        "in_market": round(in_market * 100),
        "trades": len(trades),
        "win_rate": round(float(np.mean([r > 0 for r in returns]) * 100)) if returns else None,
        "avg_trade": round(float(np.mean(returns) * 100), 1) if returns else None,
        "median_days": int(np.median([(b - a).days for a, b, _ in trades])) if trades else None,
        "trade_list": [(a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d"), round(r * 100, 1)) for a, b, r in trades],
        "equity": eq,
    }


def strategies(d: dict, sc: pd.DataFrame, start) -> dict:
    spx, ndx = d["spx"], d["ndx"]
    idx = sc.index

    def below(close, buffer=0.0):
        sma = close.rolling(200).mean()
        return (close < sma * (1 - buffer)).reindex(idx, fill_value=False)

    always = pd.Series(True, index=idx)
    never = pd.Series(False, index=idx)
    trigger = sc["trigger"].astype(bool)
    instant = (sc["score"] >= config.GREEN_FROM) & sc["trend_ok"].astype(bool)
    above_ndx = ~below(ndx)

    def buy(entries, close, buffer=0.0):
        # Nie kaufen, solange für denselben Index das Ausstiegssignal gilt
        return entries & ~below(close, buffer)

    plan = {
        "Nasdaq 100 halten (ohne Hebel)": (ndx, 1, always, never),
        "Nasdaq 100 3x halten": (ndx, 3, always, never),
        "Nasdaq 100 3x, nur über 200-Tage-Linie": (ndx, 3, above_ndx, below(ndx)),
        "Nasdaq 100 3x, nur über 200-Tage-Linie, Ausstieg 3 % darunter": (ndx, 3, above_ndx, below(ndx, 0.03)),
        "Nasdaq 100 3x, Dip-Signal + Ausstieg": (ndx, 3, buy(trigger, ndx), below(ndx)),
        "Nasdaq 100 3x, Dip sofort + Ausstieg": (ndx, 3, buy(instant, ndx), below(ndx)),
        "Nasdaq 100 3x, Dip-Signal + Ausstieg 3 % unter Linie": (ndx, 3, buy(trigger, ndx, 0.03), below(ndx, 0.03)),
        "Nasdaq 100 2x, Dip-Signal + Ausstieg": (ndx, 2, buy(trigger, ndx), below(ndx)),
        "S&P 500 halten (ohne Hebel)": (spx, 1, always, never),
        "S&P 500 2x, nur über 200-Tage-Linie": (spx, 2, ~below(spx), below(spx)),
        "S&P 500 2x, Dip-Signal + Ausstieg": (spx, 2, buy(trigger, spx), below(spx)),
    }
    return {name: simulate(c, lev, e, x, start) for name, (c, lev, e, x) in plan.items()}


def report(results: dict) -> list:
    lines = [
        "## Strategie: Kauf bei Signal, Verkauf beim Ausstiegssignal",
        "",
        "| Strategie | Endwert je 1 € | Rendite p.a. | Max. Rückgang | Zeit investiert | Trades | Gewinn-Trades | Schnitt je Trade | Haltedauer Median (Tage) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, r in results.items():
        lines.append(
            f"| {name} | {r['final']:.2f} | {r['cagr']:+.1f} % | {r['max_dd']:.1f} % | {r['in_market']} % | {r['trades']} "
            f"| {r['win_rate'] if r['win_rate'] is not None else '–'} % | {r['avg_trade'] if r['avg_trade'] is not None else '–'} % "
            f"| {r['median_days'] if r['median_days'] is not None else '–'} |"
        )
    lines.append("")
    main = results.get("Nasdaq 100 3x, Dip-Signal + Ausstieg")
    if main:
        lines += ["### Trades: Nasdaq 100 3x, Dip-Signal + Ausstieg", "", "| Kauf | Verkauf | Ergebnis |", "| --- | --- | --- |"]
        lines += [f"| {a} | {b} | {r:+.1f} % |" for a, b, r in main["trade_list"]]
        lines.append("")
    return lines
