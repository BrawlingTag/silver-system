"""Einstellungen: Indizes, Watchlist, Gewichte und Schwellen.

Alle Schwellen sind Startwerte und sollen per Backtest nachjustiert werden.
"""

# Indizes, auf die gehebelte Produkte laufen (Yahoo-Ticker -> Anzeigename)
INDEXES = {
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq 100",
    "URTH": "MSCI World",  # iShares MSCI World ETF als Stellvertreter
}
VIX = "^VIX"
VIX3M = "^VIX3M"

# Die 40 größten Growth-Werte im Nasdaq 100, grob nach Börsenwert (Stand Okt. 2026).
# Einfach hier ändern, um die Watchlist anzupassen.
WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "TSLA",
    "NFLX", "PLTR", "AMD", "ASML", "COST", "CSCO", "SHOP", "INTU",
    "ISRG", "BKNG", "APP", "MU", "LRCX", "AMAT", "QCOM", "ADBE",
    "PANW", "CRWD", "KLAC", "ARM", "MELI", "PDD", "TXN", "ADI",
    "VRTX", "DASH", "FTNT", "SNPS", "CDNS", "MRVL", "ABNB", "DDOG",
]

# Gewichte der drei Teilscores im Gesamtscore
WEIGHTS = {"angst": 0.60, "wende": 0.15, "makro": 0.25}

# Ampel (per Backtest 2007-2026 gewählt, siehe README)
RED_BELOW = 35
GREEN_FROM = 50
# Grün gibt es nur, solange der S&P 500 über seiner 200-Tage-Linie liegt.
# Im Abwärtstrend (2008, 2022) haben Dip-Käufe mit Hebel im Backtest viel Geld gekostet.
TREND_FILTER = True

# Dip-Ende: Ist der Score in den letzten SETUP_DAYS Handelstagen grün gewesen (Dip läuft),
# kommt das Kaufsignal erst, wenn der RSI über seinen kurzen Durchschnitt (RSI_MA Tage) kreuzt.
# Das Signal bleibt danach TRIGGER_HOLD Handelstage sichtbar.
RSI_TRIGGER = True
RSI_MA = 5
SETUP_DAYS = 10
TRIGGER_HOLD = 3

# Die Stabilisierungs-Säule zählt nur, wenn es vorher einen Rücksetzer gab:
# S&P 500 mindestens so weit unter dem Hoch innerhalb der letzten 20 Handelstage
DIP_MIN_DRAWDOWN = 5.0
DIP_LOOKBACK = 20

# Veto: Rezessionssignal plus schnell steigende Kreditspreads -> höchstens Gelb
VETO_SAHM = 0.5
VETO_HY_RISE = 0.75  # Prozentpunkte in 20 Handelstagen
VETO_CAP = GREEN_FROM - 5

# Score-Verlauf auf der Seite ab HISTORY_FROM; geladen wird ab HISTORY_START,
# weil 200-Tage-Linien und 52-Wochen-Hochs Vorlauf brauchen
HISTORY_START = "2004-06-01"
HISTORY_FROM = "2007-01-01"
