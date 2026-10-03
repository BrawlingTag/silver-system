import json

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


def flat(like, *legs):
    """Begleitreihe (VIX, CNN) zum Kursverlauf: (Tage, Wert) je Abschnitt, plus Startwert."""
    vals = []
    for days, v in legs:
        vals += [v] * days
    return pd.Series(vals[: len(like)], index=like.index[: len(vals)], dtype=float).reindex(like.index).ffill()


# 300 Tage Aufwärtstrend, 10 % Rücksetzer in 10 Tagen, dann zwei Tage nach oben
PANIC = ((300, 0.15), (10, -1.05), (2, 1.0))


def today(spx, vix, fg):
    sig = ind.signals(spx, vix, fg)
    pos = ind.hold_state(spx, sig["buy"])
    return sig, pos, ind.status(sig.iloc[-1], pos.iloc[-1])


def test_panic_then_rsi_turn_gives_buy():
    spx = series(*PANIC)
    sig, pos, st = today(spx, flat(spx, (301, 15), (12, 35)), flat(spx, (301, 60), (12, 12)))
    last = sig.iloc[-1]
    assert last["c_drawdown"] and last["c_vix"] and last["c_fear_greed"] and last["turn"]
    assert st["label"] == "Kaufen" and st["color"] == "green"
    assert last["score"] > 50


def test_no_buy_without_high_vix():
    spx = series(*PANIC)
    sig, _, st = today(spx, flat(spx, (313, 20)), flat(spx, (301, 60), (12, 12)))
    assert not sig["buy"].any() and st["label"] == "Kein Kaufsignal"
    assert "2 von 3" in st["text"]


def test_no_buy_without_cnn_fear():
    spx = series(*PANIC)
    sig, _, _ = today(spx, flat(spx, (301, 15), (12, 35)), flat(spx, (313, 40)))
    assert not sig["buy"].any()


def test_missing_cnn_counts_as_met():
    spx = series(*PANIC)
    sig, _, st = today(spx, flat(spx, (301, 15), (12, 35)), None)
    assert sig["buy"].iloc[-1] and st["label"] == "Kaufen"


def test_waits_while_rsi_still_falls():
    spx = series((300, 0.15), (10, -1.05))
    sig, _, st = today(spx, flat(spx, (301, 15), (10, 35)), flat(spx, (301, 60), (10, 12)))
    assert sig["setup"].iloc[-1] and not sig["buy"].iloc[-1]
    assert st["label"] == "Panik, RSI abwarten"


def test_rsi_compared_with_previous_two_days():
    idx = pd.bdate_range("2025-01-01", periods=40)
    spx = pd.Series(range(100, 140), index=idx, dtype=float)
    sig = ind.signals(spx, None)
    r = sig["rsi"]
    assert sig["rsi_ma"].iloc[-1] == (r.iloc[-2] + r.iloc[-3]) / 2


def test_score_is_50_at_the_thresholds():
    idx = pd.bdate_range("2025-01-01", periods=3)
    spx = pd.Series([100, 100, 100 * (1 - config.ATH_PCT / 100)], index=idx)
    vix = pd.Series(config.VIX_MIN, index=idx)
    fg = pd.Series(config.FG_MAX, index=idx)
    assert round(ind.signals(spx, vix, fg)["score"].iloc[-1]) == 50
    calm = ind.signals(pd.Series([100.0] * 3, index=idx), pd.Series(15.0, index=idx), pd.Series(50.0, index=idx))
    assert calm["score"].iloc[-1] == 0


def test_sell_only_3_percent_below_line():
    s = series((300, 0.1))
    sma = s.rolling(200).mean().iloc[-1]
    assert ind.exit_signal(s.where(s.index != s.index[-1], sma * 0.98))["hold"] is True
    assert ind.exit_signal(s.where(s.index != s.index[-1], sma * 0.96))["hold"] is False


def test_crash_below_line_says_sell():
    spx = series((300, 0.15), (25, -1.0))
    _, pos, _ = today(spx, flat(spx, (326, 15)), None)
    first_sell = pos.index[pos["sell"]][0]
    st = ind.status(ind.signals(spx, None).loc[first_sell], pos.loc[first_sell])
    assert st["label"] == "Verkaufen" and st["color"] == "red"


def test_stays_out_after_sell_until_back_above_line():
    spx = series((300, 0.15), (18, -1.0), (4, 1.0))
    _, pos, st = today(spx, flat(spx, (323, 15)), None)
    assert pos["sell"].any() and pos["out"].iloc[-1]
    assert st["label"] == "Draußen bleiben"
    assert ind.exit_signal(spx)["hold"] is False


def test_reentry_after_sell():
    s = series((300, 0.15), (40, -1.0), (60, 1.2))
    pos = ind.hold_state(s)
    assert pos["sell"].any() and pos["reentry"].sum() == 1
    assert pos.index[pos["reentry"]][0] > pos.index[pos["sell"]][0]


def test_buy_signal_ends_sold_state():
    s = series((300, 0.15), (30, -1.0), (3, 0.5))
    buy = pd.Series(False, index=s.index)
    buy.iloc[-2] = True
    assert ind.hold_state(s)["out"].iloc[-1]
    pos = ind.hold_state(s, buy)
    assert not pos["out"].iloc[-1] and not pos["sell"].iloc[-1]


def test_output_shape(tmp_path):
    data = run(tmp_path, crash_pct=0.08, crash_end=3)
    assert {"signal", "score", "score_parts", "rules", "info", "exits", "history", "stocks"} <= set(data)
    assert len(data["rules"]) == 4 and all(isinstance(r["ok"], bool) for r in data["rules"])
    assert len(data["score_parts"]) == 3
    assert len(data["exits"]) == 3
    h = data["history"]
    assert len(h["dates"]) == len(h["ndx"]) == len(h["sma200"]) == len(h["score"]) > 500
    assert set(h["buys"]) <= set(h["dates"]) and set(h["sells"]) <= set(h["dates"])
    assert len(data["stocks"]) == 40
    assert data["info"]["fear_greed"] is not None


def test_calm_market_has_no_signal(tmp_path):
    data = run(tmp_path, drift=0.0008)
    assert data["signal"]["label"] == "Kein Kaufsignal"
    assert data["score"] < 50


def test_missing_fear_greed_still_builds(tmp_path):
    src = FakeSource(crash_pct=0.2, crash_end=5)
    src.fear_greed = lambda **kw: None
    data = build.build(src, tmp_path / "d.json")
    assert data["info"]["fear_greed"] is None
    assert data["signal"]["label"] and data["rules"][2]["ok"]


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


def test_loop_matches_fast_hold_state():
    s = series((300, 0.15), (40, -1.0), (60, 1.2), (30, -0.8), (40, 0.9))
    buy = pd.Series(False, index=s.index)
    buy.iloc[[320, 380]] = True
    fast = ind.hold_state(s, buy)
    slow = ind._hold_loop(s, buy, None, None, None, True)
    assert (fast["out"] == slow["out"]).all()


def test_stop_below_buy_price():
    s = series((300, 0.15), (30, -1.0), (2, 0.5), (15, -1.0))
    buy = pd.Series(False, index=s.index)
    buy.iloc[331] = True
    assert not ind.hold_state(s, buy)["out"].iloc[-1]
    assert ind.hold_state(s, buy, stop=10)["out"].iloc[-1]


def test_buy_below_sell_mark_ignored_when_strict():
    s = series((300, 0.15), (30, -1.0), (3, 0.5))
    buy = pd.Series(False, index=s.index)
    buy.iloc[-2] = True
    assert ind.hold_state(s, buy, buy_overrides=False)["out"].iloc[-1]
