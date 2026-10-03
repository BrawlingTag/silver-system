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

# Die 40 größten Growth-Werte im Nasdaq 100, grob nach Börsenwert (Stand Okt. 2026).
# Einfach hier ändern, um die Watchlist anzupassen.
WATCHLIST = [
    "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "TSLA",
    "NFLX", "PLTR", "AMD", "ASML", "COST", "CSCO", "SHOP", "INTU",
    "ISRG", "BKNG", "APP", "MU", "LRCX", "AMAT", "QCOM", "ADBE",
    "PANW", "CRWD", "KLAC", "ARM", "MELI", "PDD", "TXN", "ADI",
    "VRTX", "DASH", "FTNT", "SNPS", "CDNS", "MRVL", "ABNB", "DDOG",
]

# Kaufsignal: drei einfache Regeln auf dem Nasdaq 100
SIGNAL_INDEX = "^NDX"
DIP_PCT = 6.0       # 1. Index mindestens so viel Prozent unter seinem 52-Wochen-Hoch ...
DIP_WINDOW = 10     #    ... irgendwann in den letzten 10 Handelstagen
                    # 2. Index über seiner 200-Tage-Linie
RSI_MA = 5          # 3. RSI (14 Tage) kreuzt über seinen 5-Tage-Schnitt: der Dip dreht
SIGNAL_HOLD = 3     # Kaufsignal bleibt so viele Handelstage sichtbar

# Verkaufssignal: Index schließt mehr als EXIT_BELOW Prozent unter seiner 200-Tage-Linie
EXIT_BELOW = 3.0

# Verlauf auf der Seite ab HISTORY_FROM; geladen wird ab HISTORY_START,
# weil 200-Tage-Linien und 52-Wochen-Hochs Vorlauf brauchen
HISTORY_START = "2004-06-01"
HISTORY_FROM = "2007-01-01"
