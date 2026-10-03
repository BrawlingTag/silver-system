"""Strategie-Simulation: Kauf beim Kaufsignal, Verkauf beim Verkaufssignal (Index unter 200-Tage-Linie).

Zwischen Verkauf und nächstem Kauf liegt das Geld unverzinst als Cash. Signale gelten zum Schlusskurs,
gehandelt wird damit ab dem nächsten Tag.

Zwei Arten von Hebel:
- "taeglich": Hebelprodukt mit täglicher Anpassung (ETF/ETP). Fällt der Index an einem Tag um 1/Hebel
  oder mehr (bei 5x: 20 %), ist das Produkt wertlos.
- "fest": Hebel wird beim Kauf einmal gesetzt (CFD, Future, Margin-Konto). Fällt der Index seit dem Kauf
  um 1/Hebel (bei 5x: 20 %), wird die Position liquidiert und das eingesetzte Geld ist weg.
Nach einer Liquidation ist kein Geld mehr da, die Strategie endet.
Gerechnet wird mit Schlusskursen; Liquidationen innerhalb des Tages würden früher auslösen.
"""

import numpy as np
import pandas as pd

from . import config

# Laufende Kosten pro Jahr (Gebühr plus Finanzierung des Hebels), grob 1,5 % je Hebelstufe über 1
LEVER_COST = {1: 0.0, 2: 0.015, 3: 0.03, 5: 0.06}


def daily_returns(close: pd.Series, lever: int) -> pd.Series:
    return (lever * close.pct_change() - LEVER_COST[lever] / 252).fillna(0).clip(lower=-1)


def simulate(close: pd.Series, lever: int, entries: pd.Series, exits: pd.Series, start, mode: str = "taeglich") -> dict:
    close = close.loc[start:].dropna()
    rets = daily_returns(close, lever)
    entries = entries.reindex(close.index, fill_value=False)
    exits = exits.reindex(close.index, fill_value=False)
    day_cost = 1 - LEVER_COST[lever] / 252

    equity = np.empty(len(close))
    value, invested, trades = 1.0, False, []
    entry_day = entry_value = entry_price = entry_i = None
    liquidated = None
    for i, day in enumerate(close.index):
        if invested:
            if mode == "fest":
                factor = 1 + lever * (close.iloc[i] / entry_price - 1)
                value = max(factor, 0.0) * entry_value * day_cost ** (i - entry_i)
            else:
                value *= 1 + rets.iloc[i]
            if value < 1e-9:  # Rundungsreste bei genau -20 % zählen als liquidiert
                value, liquidated = 0.0, day
        equity[i] = value
        if liquidated is not None:
            if invested:
                trades.append((entry_day, day, -1.0))
                invested = False
            continue
        if not invested and entries.iloc[i]:
            invested, entry_day, entry_value, entry_price, entry_i = True, day, value, close.iloc[i], i
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
        "liquidated": liquidated.strftime("%Y-%m-%d") if liquidated is not None else None,
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


def strategies(d: dict, sig: pd.DataFrame, start) -> dict:
    """Kauf beim Kaufsignal, Verkauf beim Verkaufssignal, verglichen mit Kaufen und Halten."""
    from . import indicators as ind

    ndx, spx = d["ndx"].dropna(), d["spx"].dropna()
    buy = sig["buy"]
    pos = ind.hold_state(ndx, buy, buy_overrides=config.BUY_BELOW_EXIT)
    pos_spx = ind.hold_state(spx, buy, buy_overrides=config.BUY_BELOW_EXIT)
    loose = ind.hold_state(ndx, buy)
    trend = ind.hold_state(ndx)
    stop10 = ind.hold_state(ndx, buy, stop=10)  # Stopp-Varianten: Kaufsignal auch unter der Verkaufsmarke
    stop20 = ind.hold_state(ndx, buy, stop=20)
    always = pd.Series(True, index=ndx.index)
    never = pd.Series(False, index=ndx.index)
    # Investiert, solange die Seite "Halten" zeigt; raus am Tag des Verkaufssignals
    follow = lambda st: (~st["out"], st["sell"])  # noqa: E731
    plan = {
        "Nasdaq 100 halten (ohne Hebel)": (ndx, 1, always, never),
        "Nasdaq 100 3x halten": (ndx, 3, always, never),
        "Nasdaq 100 2x, Regeln": (ndx, 2, *follow(pos)),
        "Nasdaq 100 3x, Regeln": (ndx, 3, *follow(pos)),
        "Nasdaq 100 3x, nur Kaufsignal ohne Wiedereinstieg": (ndx, 3, buy, pos["sell"]),
        "Nasdaq 100 3x, nur 200-Tage-Linie (ohne Kaufsignal)": (ndx, 3, *follow(trend)),
        "Nasdaq 100 3x, Kaufsignal auch unter der Verkaufsmarke": (ndx, 3, *follow(loose)),
        "Nasdaq 100 3x, Regeln, Stopp 10 % unter Kaufkurs": (ndx, 3, *follow(stop10)),
        "Nasdaq 100 3x, Regeln, Stopp 20 % unter Kaufkurs": (ndx, 3, *follow(stop20)),
        "S&P 500 3x, Regeln": (spx, 3, *follow(pos_spx)),
        "Nasdaq 100 5x täglich, Regeln": (ndx, 5, *follow(pos)),
        "Nasdaq 100 5x fest, Regeln": (ndx, 5, *follow(pos), "fest"),
    }
    return {name: simulate(*args[:4], start, *args[4:]) for name, args in plan.items()}


def report(results: dict) -> list:
    lines = [
        "## Strategie: Kauf beim Kaufsignal, Verkauf beim Verkaufssignal",
        "",
        "| Strategie | Endwert je 1 € | Rendite p.a. | Max. Rückgang | Zeit investiert | Trades | Gewinn-Trades | Schnitt je Trade | Haltedauer Median (Tage) | Liquidiert |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, r in results.items():
        lines.append(
            f"| {name} | {r['final']:.2f} | {r['cagr']:+.1f} % | {r['max_dd']:.1f} % | {r['in_market']} % | {r['trades']} "
            f"| {r['win_rate'] if r['win_rate'] is not None else '–'} % | {r['avg_trade'] if r['avg_trade'] is not None else '–'} % "
            f"| {r['median_days'] if r['median_days'] is not None else '–'} | {r['liquidated'] or 'nein'} |"
        )
    lines.append("")
    for name in ("Nasdaq 100 3x, Regeln",):
        main = results.get(name)
        if main:
            lines += [f"### Trades: {name}", "", "| Kauf | Verkauf | Ergebnis |", "| --- | --- | --- |"]
            lines += [f"| {a} | {b} | {r:+.1f} % |" for a, b, r in main["trade_list"]]
            lines.append("")
    return lines
