from dipbuy import backtest
from tests.fake_source import FakeSource


def test_backtest_finds_crash_signal():
    src = FakeSource(days=1500, crash_pct=0.3, crash_end=300, recovery=0.5)
    result = backtest.run(src)
    green = result["signals"]["ab 60, ohne Filter, sofort"]
    assert green["summary"]["count"] >= 1
    row = green["rows"][-1]
    assert row["dd_at_signal"] > 5
    assert row["days_peak_to_signal"] > 0
    assert row["spx_3M"] is not None
    text = backtest.report(result)
    assert "Anzahl Signale" in text and "Zum Vergleich" in text


def test_episodes_debounce():
    import pandas as pd
    idx = pd.bdate_range("2020-01-01", periods=200)
    s = pd.Series(0.0, index=idx)
    s.iloc[10:15] = 70
    s.iloc[30:32] = 70   # zu nah, gleiche Phase
    s.iloc[150:155] = 70  # neue Phase
    assert backtest.episodes(s, 65) == [idx[10], idx[150]]


def test_simulate_enters_and_exits():
    import pandas as pd
    from dipbuy import strategy
    idx = pd.bdate_range("2020-01-01", periods=6)
    close = pd.Series([100, 100, 110, 121, 100, 100], index=idx, dtype=float)
    entries = pd.Series([False, True, False, False, False, False], index=idx)
    exits = pd.Series([False, False, False, True, False, False], index=idx)
    r = strategy.simulate(close, 1, entries, exits, idx[0])
    # gekauft zum Schluss von Tag 2, verkauft zum Schluss von Tag 4: +10 % und +10 %
    assert r["trades"] == 1
    assert r["final"] == 1.21
    assert r["trade_list"][0][2] == 21.0


def test_trigger_needs_uptrend_on_buy_day():
    import pandas as pd
    from dipbuy import indicators as ind

    idx = pd.bdate_range("2024-01-01", periods=12)
    score = pd.Series([60.0] * 12, index=idx)
    r = pd.Series([50, 45, 40, 35, 30, 28, 26, 25, 24, 35, 45, 50], index=idx, dtype=float)
    trend = pd.Series(True, index=idx)
    _, trigger = ind.dip_entry(score, trend, r, ma=3, setup_days=10)
    assert trigger.any()

    broken = trend.copy()
    broken.iloc[5:] = False  # Trend bricht während des Dips
    setup, trigger = ind.dip_entry(score, broken, r, ma=3, setup_days=10)
    assert setup.iloc[-1] and not trigger.any()
    assert ind.signal(60.0, False, True, False)["label"] == "Dip im Abwärtstrend"
