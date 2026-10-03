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

# Kaufsignal: Panik am Markt, dann dreht der RSI nach oben
SIGNAL_INDEX = "^GSPC"
ATH_PCT = 4.0       # 1. S&P 500 mindestens so viel Prozent unter seinem Allzeithoch
VIX_MIN = 26.0      # 2. VIX über diesem Wert
FG_MAX = 21.0       # 3. CNN Fear & Greed unter diesem Wert
SETUP_WINDOW = 10   #    Die drei Bedingungen zählen, wenn sie in den letzten 10 Handelstagen erfüllt waren
RSI_MA = 2          # 4. RSI (14 Tage) des S&P 500 über dem Schnitt der letzten 2 Tage: die Panik dreht
SIGNAL_HOLD = 3     # Kauf- und Verkaufssignale bleiben so viele Handelstage sichtbar

# Score 0-100: je tiefer der S&P unter dem Hoch, je höher der VIX und je tiefer CNN, desto höher.
# Jeder Teil: ruhig = 0, Schwelle = 50, extrem = 100 Punkte; der Score ist der Schnitt der Teile.
SCORE_PARTS = {
    "drawdown": (0.0, ATH_PCT, 20.0),
    "vix": (15.0, VIX_MIN, 45.0),
    "fear_greed": (50.0, FG_MAX, 0.0),
}

# Verkaufen, Wiedereinstieg und Verlauf laufen auf dem Nasdaq 100 (darauf wird gehebelt gekauft)
TRADE_INDEX = "^NDX"

# Verkaufssignal: Index schließt mehr als EXIT_BELOW Prozent unter seiner 200-Tage-Linie
EXIT_BELOW = 3.0
# Kaufsignal auch dann befolgen, wenn der Nasdaq 100 unter der Verkaufsmarke liegt (Bärenmarkt)?
# Paul: ja (3. Okt. 2026). Im Backtest 2007-2026 mit 3x: 149 € bei größtem Verlust -93 %; mit False 150 € bei -76 %.
BUY_BELOW_EXIT = True

# Verlauf auf der Seite ab HISTORY_FROM; geladen wird ab HISTORY_START,
# weil 200-Tage-Linien und das Allzeithoch Vorlauf brauchen
HISTORY_START = "1990-01-01"
HISTORY_FROM = "2007-01-01"
