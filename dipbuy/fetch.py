"""Datenabruf aus öffentlichen Quellen. Jede Quelle darf ausfallen; dann fehlt nur ihr Indikator."""

import io
import logging
import time
from datetime import date, timedelta

import pandas as pd
import requests
import yfinance as yf

log = logging.getLogger(__name__)

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}


def _download(tickers: list[str], span: dict, threads: bool) -> pd.DataFrame:
    data = yf.download(tickers, **span, auto_adjust=True, progress=False, threads=threads)
    df = data["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame(tickers[0])
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


def closes(tickers: list[str], period: str = "3y", start: str | None = None) -> pd.DataFrame:
    """Schlusskurse (dividendenbereinigt) als DataFrame, eine Spalte je Ticker.

    Beim parallelen Download sperrt sich yfinance gelegentlich selbst ("database is locked");
    fehlende Ticker werden deshalb einmal nacheinander nachgeladen.
    """
    span = {"start": start} if start else {"period": period}
    df = _download(tickers, span, threads=True)
    missing = [t for t in tickers if t not in df or df[t].dropna().empty]
    if missing:
        log.info("Lade %d fehlende Ticker nach: %s", len(missing), ", ".join(missing[:10]))
        retry = _download(missing, span, threads=False)
        for t in missing:
            if t in retry and not retry[t].dropna().empty:
                df = df.drop(columns=t, errors="ignore").join(retry[t], how="outer")
    return df


def fear_greed(days: int = 800) -> pd.Series | None:
    """CNN Fear & Greed, inoffizieller Endpunkt der CNN-Seite.

    Sehr frühe Startdaten lehnt CNN mit einem Serverfehler ab; dann wird mit 800 Tagen neu versucht.
    """
    headers = {**UA, "Referer": "https://edition.cnn.com/", "Origin": "https://edition.cnn.com"}
    for span in dict.fromkeys([days, 800]):
        start = (date.today() - timedelta(days=span)).isoformat()
        url = f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start}"
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            js = r.json()
            rows = js["fear_and_greed_historical"]["data"]
            s = pd.Series(
                [p["y"] for p in rows],
                index=pd.to_datetime([p["x"] for p in rows], unit="ms").normalize(),
                name="fear_greed",
            )
            s = s[~s.index.duplicated(keep="last")].sort_index()
            # Der aktuelle Wert steht separat und ist oft neuer als die Historie
            now = js.get("fear_and_greed", {})
            if "score" in now and "timestamp" in now:
                ts = pd.to_datetime(now["timestamp"]).tz_localize(None).normalize()
                s.loc[ts] = float(now["score"])
            return s.sort_index()
        except Exception as e:  # noqa: BLE001
            log.warning("Fear & Greed ab %s nicht abrufbar: %s", start, e)
    return None


def fred(series_id: str, tries: int = 3, days: int = 1500) -> pd.Series | None:
    """Zeitreihe der US-Notenbank St. Louis (FRED), ohne API-Key über den CSV-Export.

    Der Export antwortet manchmal sehr langsam, darum nur die letzten Jahre und mehrere Versuche.
    """
    start = (date.today() - timedelta(days=days)).isoformat()
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = ["date", "value"]
            return pd.Series(
                pd.to_numeric(df["value"], errors="coerce").to_numpy(),
                index=pd.to_datetime(df["date"]),
                name=series_id,
            ).dropna()
        except Exception as e:  # noqa: BLE001
            log.warning("FRED %s nicht abrufbar (Versuch %d/%d): %s", series_id, attempt, tries, e)
            time.sleep(5 * attempt)
    return None


def sp500_tickers() -> list[str] | None:
    try:
        r = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=UA, timeout=30)
        r.raise_for_status()
        table = pd.read_html(io.StringIO(r.text), attrs={"id": "constituents"})[0]
        return [t.replace(".", "-") for t in table["Symbol"].astype(str)]
    except Exception as e:  # noqa: BLE001
        log.warning("S&P-500-Liste nicht abrufbar: %s", e)
        return None


def breadth(start: str | None = None) -> pd.Series | None:
    """Anteil der S&P-500-Aktien über ihrer 200-Tage-Linie in Prozent."""
    tickers = sp500_tickers()
    if not tickers:
        return None
    try:
        df = closes(tickers, period="3y", start=start)
        sma = df.rolling(200).mean()
        valid = sma.notna() & df.notna()
        above = (df > sma) & valid
        pct = above.sum(axis=1) / valid.sum(axis=1).replace(0, float("nan")) * 100
        return pct[valid.sum(axis=1) > 300].rename("breadth")
    except Exception as e:  # noqa: BLE001
        log.warning("Marktbreite nicht berechenbar: %s", e)
        return None


def analyst_info(ticker: str) -> dict:
    """Konsens-Kursziel, Rating (1 = Strong Buy, 5 = Sell) und Revision der Gewinnschätzung (90 Tage)."""
    out = {}
    t = yf.Ticker(ticker)
    try:
        info = t.info
        out["name"] = info.get("shortName") or ticker
        out["target"] = info.get("targetMeanPrice")
        out["rating"] = info.get("recommendationMean")
        out["analysts"] = info.get("numberOfAnalystOpinions")
    except Exception as e:  # noqa: BLE001
        log.warning("Analystendaten %s: %s", ticker, e)
    try:
        trend = t.eps_trend
        row = trend.loc["+1y"] if "+1y" in trend.index else trend.loc["0y"]
        cur, old = float(row["current"]), float(row["90daysAgo"])
        if old and old > 0:
            out["revision"] = (cur / old - 1) * 100
    except Exception as e:  # noqa: BLE001
        log.warning("Gewinnrevisionen %s: %s", ticker, e)
    return out
