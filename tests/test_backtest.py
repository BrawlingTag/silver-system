from dipbuy import backtest
from tests.fake_source import FakeSource


def test_backtest_finds_crash_signal():
    src = FakeSource(days=1500, crash_pct=0.3, crash_end=300, recovery=0.5)
    result = backtest.run(src)
    green = result["signals"]["ab 60"]
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
