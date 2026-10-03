# Dip-Buy

Eine kleine Web-App, die jeden US-Handelstag prüft, ob gerade ein guter Moment ist, gehebelt in den Nasdaq 100 (oder Growth-Aktien) einzusteigen, um eine Erholung nach einem Rücksetzer mitzunehmen.

Die Seite läuft kostenlos auf GitHub Pages und aktualisiert sich automatisch werktags nach US-Börsenschluss.

## Die Regeln

**Kaufen**, wenn am selben Tag alle drei Regeln erfüllt sind:

1. **Rücksetzer:** Der Nasdaq 100 war in den letzten 10 Handelstagen mindestens 6 % unter seinem 52-Wochen-Hoch.
2. **Aufwärtstrend:** Der Nasdaq 100 schließt über seiner 200-Tage-Linie.
3. **Dip dreht:** Der RSI (14 Tage) kreuzt über seinen 5-Tage-Schnitt.

**Wieder einsteigen**, wenn der Nasdaq 100 nach einem Verkauf zurück über seiner 200-Tage-Linie schließt.

**Verkaufen**, wenn der Index mehr als 3 % unter seiner 200-Tage-Linie schließt.

Im Backtest 2007 bis 2026 machte Nasdaq 100 mit 3x Hebel nach diesen Regeln aus 1 € rund 143 € (+28,6 % pro Jahr, größter Verlust −64 %). Dauerhaft 3x halten brachte 138 € bei −95 %, ohne Hebel 18 €. Ohne den Wiedereinstieg wären es nur 18 € gewesen, weil man nach einem Verkauf große Erholungen verpasst.

CNN Fear & Greed und VIX stehen als Info auf der Seite, entscheiden aber nichts. Die Watchlist bewertet 40 große Growth-Werte aus dem Nasdaq 100 nach Rücksetzer, RSI, Kursziel-Abstand, Analysten-Rating und Änderung der Gewinnschätzung. Alle Werte stehen in `dipbuy/config.py`.

## Aufbau

- `dipbuy/fetch.py` holt die Daten (Yahoo Finance, CNN). Fällt CNN aus, fehlt nur die Fear-&-Greed-Anzeige.
- `dipbuy/indicators.py` prüft die Regeln für jeden Tag.
- `dipbuy/build.py` schreibt alles nach `site/data.json`.
- `site/index.html` ist die Seite. Der Verlauf reicht bis 2007 zurück, mit Zeitraumauswahl, Vollbild sowie Kauf- und Verkaufssignalen als Punkte.
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
