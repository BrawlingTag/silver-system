import pandas as pd

from dipbuy import backtest
from tests.fake_source import FakeSource


def test_backtest_runs_and_reports():
    src = FakeSource(days=1500, crash_pct=0.1, crash_len=10, crash_end=300, recovery=0.2, drift=0.0015)
    result = backtest.run(src)
    assert result["summary"]["count"] >= 1
    row = result["signals"][0]
    assert row["drawdown"] >= 6 and row["ndx_3M"] is not None
    assert len(result["sensitivity"]) == len(backtest.DIP_PCTS) * len(backtest.RSI_MAS)
    text = backtest.report(result)
    assert "Kaufsignale" in text and "Strategie" in text and "Andere Einstellungen" in text


def test_first_signals_debounce():
    idx = pd.bdate_range("2020-01-01", periods=200)
    buy = pd.Series(False, index=idx)
    buy.iloc[[10, 12, 30, 150]] = True  # 12 und 30 gehören zum selben Dip
    assert backtest.first_signals(buy) == [idx[10], idx[150]]


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


def test_simulate_5x_liquidation():
    import pandas as pd
    from dipbuy import strategy
    idx = pd.bdate_range("2020-01-01", periods=6)
    entries = pd.Series([True, False, False, False, True, False], index=idx)
    exits = pd.Series(False, index=idx)

    # Täglicher Hebel: ein Tag mit -20 % macht ein 5x-Produkt wertlos
    crash = pd.Series([100, 100, 80, 100, 100, 110], index=idx, dtype=float)
    r = strategy.simulate(crash, 5, entries, exits, idx[0])
    assert r["final"] == 0 and r["liquidated"] == "2020-01-03" and r["trades"] == 1

    # Fester Hebel: -20 % seit Kauf, verteilt auf mehrere Tage, liquidiert ebenfalls
    slide = pd.Series([100, 95, 90, 85, 80, 120], index=idx, dtype=float)
    r = strategy.simulate(slide, 5, entries, exits, idx[0], mode="fest")
    assert r["final"] == 0 and r["liquidated"] == "2020-01-07"

    # Täglicher Hebel übersteht denselben Abstieg (Tagesverluste unter 20 %)
    r = strategy.simulate(slide, 5, entries, exits, idx[0])
    assert r["liquidated"] is None and r["final"] > 0
