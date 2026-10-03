# Dip-Buy

Eine kleine Web-App, die jeden US-Handelstag prüft, ob gerade ein guter Moment ist, gehebelt in den Nasdaq 100 (oder Growth-Aktien) einzusteigen, um eine Erholung nach einem Rücksetzer mitzunehmen.

Die Seite läuft kostenlos auf GitHub Pages und aktualisiert sich automatisch werktags nach US-Börsenschluss.

## Die Regeln

**Score (0 bis 100):** Je tiefer der S&P 500 unter seinem Allzeithoch, je höher der VIX und je tiefer CNN Fear & Greed, desto höher der Score und desto stärker das Kaufsignal. Jeder der drei Teile hat an seiner Schwelle 50 Punkte.

**Kaufen**, wenn Panik am Markt ist und sie dreht. Panik heißt: In den letzten 10 Handelstagen war

1. der S&P 500 mindestens 4 % unter seinem Allzeithoch,
2. der VIX über 26 und
3. CNN Fear & Greed unter 21.

Gekauft wird, sobald dann der RSI (14 Tage) des S&P 500 über dem Schnitt der letzten 2 Tage liegt. So steigt man nicht ein, solange es noch keine Erholung gibt.

**Verkaufen** 2 Handelstage, nachdem CNN Fear & Greed über 85 gestiegen ist (extreme Gier). Danach draußen bis zum nächsten Kaufsignal.

Im Backtest 2007 bis 2026 gab es kein einziges Verkaufssignal: CNN-Werte gibt es erst ab Juli 2024, und seitdem lag CNN nie über 85. Nasdaq 100 mit 3x Hebel entspricht damit dem Dauerhalten: aus 1 € wurden 138 €, der größte Verlust war −95 % (2008). Die Kaufsignale allein waren nicht besser als ein beliebiger Tag: im Schnitt +8,7 % nach 3 Monaten mit 3x, gegenüber +11,0 % an irgendeinem Tag.

CNN Fear & Greed gibt es erst ab Mitte 2024; im Backtest zählt davor beim Kauf nur S&P 500 und VIX, und es gibt keine Verkaufssignale. Die Watchlist bewertet 40 große Growth-Werte aus dem Nasdaq 100 nach Rücksetzer, RSI, Kursziel-Abstand, Analysten-Rating und Änderung der Gewinnschätzung. Alle Werte stehen in `dipbuy/config.py`.

## Aufbau

- `dipbuy/fetch.py` holt die Daten (Yahoo Finance, CNN). Fällt CNN aus, zählt die CNN-Bedingung als erfüllt.
- `dipbuy/indicators.py` berechnet Score, Kauf- und Verkaufssignal für jeden Tag.
- `dipbuy/build.py` schreibt alles nach `site/data.json`.
- `site/index.html` ist die Seite. Der Verlauf reicht bis 2007 zurück: Nasdaq 100, S&P 500, MSCI World oder MSCI ACWI, darunter der Score, mit Zeitraumauswahl, Vollbild sowie Kauf- und Verkaufssignalen als Punkte.
- `.github/workflows/update.yml` läuft werktags um 22:15 UTC, testet, rechnet und veröffentlicht.

Lokal ausprobieren:

```
pip install -r requirements.txt
python -m dipbuy.build site/data.json
cd site && python -m http.server
```

Keine Anlageberatung.

## Backtest

`python -m dipbuy.backtest` prüft die Regeln ab 2007: wie oft ein Kaufsignal kam, wie weit der Nasdaq danach noch fiel, und was Kaufen beim Kaufsignal und Verkaufen beim Verkaufssignal mit 1x, 2x, 3x und 5x Hebel gebracht hätte. Auf GitHub läuft er unter Actions → Backtest → "Run workflow".
