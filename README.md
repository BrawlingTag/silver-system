# Dip-Buy-Score

Eine kleine Web-App, die jeden US-Handelstag einen Score von 0 bis 100 berechnet: Lohnt es sich gerade, gehebelte Indizes (S&P 500, Nasdaq 100, MSCI World) oder Growth-Aktien zu kaufen, um eine Markterholung mitzunehmen?

Die Seite läuft kostenlos auf GitHub Pages und aktualisiert sich automatisch werktags nach US-Börsenschluss.

## Wie der Score entsteht

| Teilscore | Gewicht | Indikatoren |
| --- | --- | --- |
| Angst im Markt | 45 % | CNN Fear & Greed, VIX, VIX/VIX3M, Abstand der Indizes vom Hoch, Anteil S&P-500-Aktien über 200-Tage-Linie |
| Wende-Bestätigung | 35 % | RSI dreht aus überverkauft, Index zurück über 20- und 50-Tage-Linie, VIX fällt vom Hoch. Zählt nur nach einem Rücksetzer von mindestens 8 %. |
| Makro | 20 % | High-Yield-Spread (Niveau und Änderung), Sahm-Regel |

- **Ampel:** unter 40 Rot (abwarten), 40 bis 65 Gelb (Teilposition), ab 65 Grün (2x), ab 80 auch 3x vertretbar.
- **Veto:** Löst die Sahm-Regel aus und steigen die Kreditspreads schnell, bleibt der Score höchstens Gelb.
- **Ausstiegssignal:** Hebel nur halten, solange der Index über seiner 200-Tage-Linie liegt.
- **Watchlist:** 40 große Growth-Werte aus dem Nasdaq 100, bewertet nach Rücksetzer, RSI, Kursziel-Abstand, Analysten-Rating und Änderung der Gewinnschätzung.

Alle Schwellen und Gewichte stehen in `dipbuy/config.py` und sind Startwerte, die noch per Backtest kalibriert werden sollen.

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
