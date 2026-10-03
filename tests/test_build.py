import json

import pandas as pd

from dipbuy import build, config, indicators as ind
from tests.fake_source import FakeSource


def run(tmp_path, **kw):
    out = tmp_path / "data.json"
    build.build(FakeSource(**kw), out)
    return json.loads(out.read_text())


def test_calm_market_is_red(tmp_path):
    data = run(tmp_path)
    assert data["signal"]["color"] == "red"
    assert data["sub"]["wende"] == 0
    assert all(e["hold"] for e in data["exits"])


def test_crash_below_200_day_line_is_only_yellow(tmp_path):
    data = run(tmp_path, crash_pct=0.25, crash_end=0)
    assert data["sub"]["angst"] > 80
    assert not data["trend_ok"]
    assert data["signal"]["label"] == "Dip im Abwärtstrend"


def test_small_correction_raises_score(tmp_path):
    calm = run(tmp_path)["score"]
    small = run(tmp_path, crash_pct=0.03, crash_len=10, crash_end=0)["score"]
    six = run(tmp_path, crash_pct=0.06, crash_len=10, crash_end=0)
    assert calm < small < six["score"]
    # im intakten Aufwärtstrend wird aus der 6-%-Korrektur ein Kaufsignal
    six = run(tmp_path, crash_pct=0.06, crash_len=10, crash_end=0, drift=0.0012)
    assert six["trend_ok"]
    assert six["signal"]["label"] == "Dip läuft", six["score"]


def test_rsi_turn_after_correction_gives_buy(tmp_path):
    data = run(tmp_path, crash_pct=0.06, crash_len=10, crash_end=2, recovery=0.01, drift=0.0012)
    assert data["trend_ok"]
    assert data["signal"]["label"] == "Dip-Ende: kaufen", (data["score"], data["signal"])


def test_rsi_cross_up():
    idx = pd.bdate_range("2025-01-01", periods=8)
    r = pd.Series([50, 40, 30, 25, 22, 28, 35, 40], index=idx, dtype=float)
    cross = ind.rsi_cross_up(r, 3)
    assert list(cross[cross].index) == [idx[5]]


def test_recovery_shows_stabilisation(tmp_path):
    data = run(tmp_path, crash_pct=0.25, crash_end=8, recovery=0.08)
    assert data["dip"]
    assert data["sub"]["wende"] > 50


def test_output_shape(tmp_path):
    data = run(tmp_path, crash_pct=0.2, crash_end=5, recovery=0.03)
    assert 0 <= data["score"] <= 100
    assert len(data["history"]["dates"]) == len(data["history"]["score"]) > 300
    assert len(data["stocks"]) == 40
    assert {"angst", "wende", "makro"} == set(data["parts"])


def test_veto_caps_score(tmp_path):
    src = FakeSource(crash_pct=0.3, crash_end=8, recovery=0.1)
    hy = pd.Series(4.0, index=src.idx)
    hy.iloc[-20:] = [4.0 + 0.1 * i for i in range(20)]
    src.fred = lambda sid: pd.Series(0.7, index=src.idx) if sid == "SAHMREALTIME" else hy
    out = tmp_path / "d.json"
    data = build.build(src, out)
    assert data["veto"]
    assert data["score"] <= config.VETO_CAP


def test_missing_sources_still_build(tmp_path):
    src = FakeSource(crash_pct=0.2, crash_end=5)
    src.fear_greed = lambda: None
    src.breadth = lambda: None
    src.fred = lambda sid: None
    data = build.build(src, tmp_path / "d.json")
    assert data["sub"]["makro"] is None
    assert 0 <= data["score"] <= 100


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
