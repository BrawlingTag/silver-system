"""Synthetische Datenquelle mit derselben Schnittstelle wie dipbuy.fetch, für Tests ohne Internet."""

import numpy as np
import pandas as pd


class FakeSource:
    """Ruhiger Aufwärtstrend, dann ein Crash um `crash_pct` und optional eine Erholung.

    `crash_end` = Handelstage vor dem Ende, an denen der Tiefpunkt liegt.
    """

    def __init__(self, days=750, crash_pct=0.0, crash_len=25, crash_end=10, recovery=0.0, seed=1, drift=0.0005):
        self.idx = pd.bdate_range(end="2026-10-02", periods=days)
        rng = np.random.default_rng(seed)
        ret = rng.normal(drift, 0.0025, days)
        bottom = days - 1 - crash_end
        start = bottom - crash_len
        if crash_pct:
            ret[start:bottom] += np.log(1 - crash_pct) / crash_len
            if recovery and crash_end:
                ret[bottom:] += np.log(1 + recovery) / crash_end
        self.base = pd.Series(np.exp(np.cumsum(ret)), index=self.idx)
        stress = (1 - self.base / self.base.cummax()).clip(lower=0)
        self.stress = stress
        self.vix = 14 + stress * 160

    def closes(self, tickers, period="3y", start=None):
        cols = {}
        for i, t in enumerate(tickers):
            if t == "^VIX":
                cols[t] = self.vix
            else:
                cols[t] = 100 * self.base ** (1 + 0.1 * (i % 5))
        return pd.DataFrame(cols)

    def fear_greed(self, days=800):
        return (60 - self.stress * 300).clip(5, 90)

    def analyst_info(self, ticker):
        return {"name": ticker, "target": 400.0, "rating": 1.8, "analysts": 40, "revision": 2.0}
