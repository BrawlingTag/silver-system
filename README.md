# Dip-Buy-Score

Eine kleine Web-App, die jeden US-Handelstag einen Score von 0 bis 100 berechnet: Lohnt es sich gerade, gehebelte Indizes (S&P 500, Nasdaq 100, MSCI World) oder Growth-Aktien zu kaufen, um eine Markterholung mitzunehmen?

Die Seite läuft kostenlos auf GitHub Pages und aktualisiert sich automatisch werktags nach US-Börsenschluss.

## Wie der Score entsteht

| Teilscore | Gewicht | Indikatoren |
| --- | --- | --- |
| Angst im Markt | 60 % | CNN Fear & Greed, VIX, VIX/VIX3M, RSI (überverkauft zählt sofort), Abstand der Indizes vom Hoch, Anteil S&P-500-Aktien über 200-Tage-Linie. Skaliert so, dass schon eine Korrektur von rund 6 % deutlich zählt. |
| Stabilisierung | 15 % | VIX kommt vom 10-Tage-Hoch zurück, Index erholt sich vom 5-Tage-Tief. Zählt nur nach einem Rücksetzer von mindestens 5 %. |
| Makro | 25 % | High-Yield-Spread (für ältere Daten Baa-Spread), Änderung über 20 Tage, Sahm-Regel |

- **Ampel:** unter 35 Rot (kein Dip), 35 bis 50 Gelb (leichter Rücksetzer), ab 50 Grün (Dip kaufen, 2x, mit viel Risikobereitschaft 3x).
- **Trendfilter:** Grün nur, solange der S&P 500 über seiner 200-Tage-Linie liegt. Darunter bleibt es Gelb.
- **Veto:** Löst die Sahm-Regel aus und steigen die Kreditspreads schnell, bleibt der Score höchstens Gelb.
- **Ausstiegssignal:** Hebel nur halten, solange der Index über seiner 200-Tage-Linie liegt.
- **Watchlist:** 40 große Growth-Werte aus dem Nasdaq 100, bewertet nach Rücksetzer, RSI, Kursziel-Abstand, Analysten-Rating und Änderung der Gewinnschätzung.

Backtest 2007 bis 2026 mit diesen Einstellungen: 44 Signale (rund 2 pro Jahr), Median 27 Tage vom Hoch bis zum Signal. Nasdaq 100 mit 3x Hebel lag 3 Monate nach einem Signal im Schnitt bei +20,7 % (81 % der Fälle positiv), bei einem Kauf an einem beliebigen Tag bei +11,0 %. Alle Schwellen stehen in `dipbuy/config.py`.

## Aufbau

- `dipbuy/fetch.py` holt die Daten (Yahoo Finance, CNN, FRED, Wikipedia). Fällt eine Quelle aus, fehlt nur ihr Indikator.
- `dipbuy/indicators.py` rechnet Indikatoren und Scores.
- `dipbuy/build.py` schreibt alles nach `site/data.json`.
- `site/index.html` ist die Seite.
- `.github/workflows/update.yml` läuft werktags um 22:15 UTC, testet, rechnet und veröffentlicht.

Lokal ausprobieren:

```
pip install -r requirements.txt
python -m dipbuy.build site/data.json
cd site && python -m http.server
```

Keine Anlageberatung.

## Backtest

`python -m dipbuy.backtest` rechnet den Score ab 2007 rückwirkend und wertet jedes Kaufsignal aus: wie lange nach dem Hoch es kam, ob vor oder nach dem Tiefpunkt, und wie sich S&P 500, Nasdaq 100 und gehebelte Varianten danach entwickelt haben. Auf GitHub läuft er unter Actions → Backtest → "Run workflow".
