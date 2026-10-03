import json

import numpy as np
import pandas as pd

from dipbuy import build, config, indicators as ind
from tests.fake_source import FakeSource


def run(tmp_path, **kw):
    out = tmp_path / "data.json"
    build.build(FakeSource(**kw), out)
    return json.loads(out.read_text())


def series(*legs, start=100.0):
    """Kursverlauf aus Abschnitten (Tage, Rendite pro Tag in Prozent)."""
    vals = [start]
    for days, pct in legs:
        for _ in range(days):
            vals.append(vals[-1] * (1 + pct / 100))
    return pd.Series(vals, index=pd.bdate_range("2020-01-01", periods=len(vals)), dtype=float)


def test_calm_market_has_no_dip(tmp_path):
    data = run(tmp_path, drift=0.0008)
    assert data["signal"]["label"] == "Kein Dip"
    assert [r["ok"] for r in data["rules"]] == [False, True, False] or not data["rules"][0]["ok"]


def test_crash_below_200_day_line_says_sell(tmp_path):
    data = run(tmp_path, crash_pct=0.3, crash_end=5)
    assert data["signal"]["label"] == "Verkaufen"
    assert data["signal"]["color"] == "red"


def test_correction_in_uptrend_then_turn_gives_buy():
    # 300 Tage Aufwärtstrend, 8 % Rücksetzer in 8 Tagen, dann zwei Tage nach oben
    s = series((300, 0.15), (8, -1.04), (2, 1.0))
    rl = ind.rules(s)
    last = rl.iloc[-1]
    assert last["dip"] and last["trend"] and last["buy_recent"]
    assert ind.status(last)["label"] == "Kaufen"


def test_no_buy_without_dip():
    # Nur 3 % Rücksetzer: RSI dreht zwar, aber das reicht nicht
    s = series((300, 0.15), (6, -0.5), (2, 1.0))
    rl = ind.rules(s)
    assert not rl["dip"].iloc[-1] and not rl["buy"].any()


def test_no_buy_below_200_day_line():
    # Langer Abwärtstrend unter der Linie, dann kurzer Anstieg: Rücksetzer ja, Trend nein
    s = series((300, 0.1), (120, -0.3), (2, 1.0))
    rl = ind.rules(s)
    assert rl["dip"].iloc[-1] and not rl["trend"].iloc[-1] and not rl["buy"].iloc[-1]


def test_sell_only_3_percent_below_line():
    s = series((300, 0.1))
    sma = s.rolling(200).mean().iloc[-1]
    assert ind.exit_signal(s.where(s.index != s.index[-1], sma * 0.98))["hold"] is True
    assert ind.exit_signal(s.where(s.index != s.index[-1], sma * 0.96))["hold"] is False


def test_rsi_cross_up():
    idx = pd.bdate_range("2025-01-01", periods=8)
    r = pd.Series([50, 40, 30, 25, 22, 28, 35, 40], index=idx, dtype=float)
    cross = ind.rsi_cross_up(r, 3)
    assert list(cross[cross].index) == [idx[5]]


def test_output_shape(tmp_path):
    data = run(tmp_path, crash_pct=0.08, crash_end=3)
    assert {"signal", "rules", "info", "exits", "history", "stocks"} <= set(data)
    assert len(data["rules"]) == 3 and all(isinstance(r["ok"], bool) for r in data["rules"])
    assert len(data["exits"]) == 3
    h = data["history"]
    assert len(h["dates"]) == len(h["ndx"]) == len(h["sma200"]) > 500
    assert set(h["buys"]) <= set(h["dates"]) and set(h["sells"]) <= set(h["dates"])
    assert len(data["stocks"]) == 40
    assert data["info"]["fear_greed"] is not None


def test_missing_fear_greed_still_builds(tmp_path):
    src = FakeSource(crash_pct=0.2, crash_end=5)
    src.fear_greed = lambda **kw: None
    data = build.build(src, tmp_path / "d.json")
    assert data["info"]["fear_greed"] is None
    assert data["signal"]["label"]


def test_exit_signal_below_sma200():
    s = pd.Series(range(300, 0, -1), index=pd.bdate_range("2025-01-01", periods=300), dtype=float)
    e = ind.exit_signal(s)
    assert e["hold"] is False and e["distance"] < 0


def test_stock_score_prefers_dip_with_rising_estimates():
    idx = pd.bdate_range("2025-01-01", periods=300)
    up = pd.Series([100 + i * 0.3 for i in range(300)], index=idx)
    down = pd.Series([100 + i * 0.3 for i in range(250)] + [175 - i * 1.5 for i in range(50)], index=idx)
    info = {"target": 200.0, "rating": 1.7, "revision": 3.0}
    assert ind.stock_score(down, info)["score"] > ind.stock_score(up, info)["score"]
