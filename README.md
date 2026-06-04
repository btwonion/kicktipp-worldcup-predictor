# Kicktipp Worldcup Predictor

Ein kleines lokales Python-Tool, das für Fussballspiele Kicktipp-Tipps nach Erwartungswert sortiert. Es nutzt ein Poisson-Modell für exakte Ergebniswahrscheinlichkeiten und bewertet jeden moeglichen Tipp mit der Kicktipp-Punktelogik.

Das Tool ist auf WM-Spiele und andere Fussballspiele anwendbar. Standardmäßig nutzt es alle verfügbaren Datenquellen automatisch. Für erwartete Gesamttore verwendet es entweder manuelle Werte oder automatisch geladene Over/Under-Quoten; ohne solche Daten bricht es bewusst ab.

## Was das Tool macht

- lädt Spielpaarungen, 1X2-Wahrscheinlichkeiten und, sofern verfügbar, Total-Goals-Quoten automatisch aus den verfügbaren Quellen
- lädt Elo-Ratings aus einer lokalen CSV-Datei, per Remote-Quelle oder akzeptiert manuelle Elo-Werte
- akzeptiert manuelle Werte als Override, wenn eine Quelle fehlt oder bewusst überschrieben werden soll
- leitet daraus erwartete Tore für Team A und Team B ab
- erzeugt eine normalisierte Score-Matrix, standardmässig bis 6:6
- berechnet für jeden Tipp bis 5:5 den erwarteten Kicktipp-Punktwert
- gibt den besten Tipp und die Top 5 aus

## Was es nicht kann

Dieses Tool gibt keine sicheren Vorhersagen. Es optimiert Tipps anhand modellierter Wahrscheinlichkeiten und der Kicktipp-Punktelogik. Die Qualität hängt stark von aktuellen Eingabedaten wie Quoten, Aufstellungen, Verletzungen und Teamstärke ab.

Es ersetzt keine Marktanalyse und keine aktuellen Team-News. Fehlende 1X2-Daten werden aus der nächsten verfügbaren Quelle geladen. Fehlende erwartete Gesamttore werden nicht still geschätzt, weil dieser Wert die Score-Verteilung stark beeinflusst.

## Warum Erwartungswert wichtiger ist als der wahrscheinlichste Score

Kicktipp belohnt nicht nur exakte Ergebnisse. Ein 1:0-Tipp bekommt auch Punkte für andere Siege mit gleicher Tordifferenz oder gleicher Tendenz. Deshalb kann der beste Kicktipp-Tipp ein anderer sein als das wahrscheinlichste einzelne Ergebnis.

Das Tool berechnet:

```text
EV(tipp) = Summe P(tatsächliches Ergebnis) * KicktippPunkte(tipp, tatsächliches Ergebnis)
```

Dadurch wird direkt auf den erwarteten Punktwert optimiert.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Standardnutzung

Das Tool geht davon aus, dass alle Datenquellen grundsätzlich verfügbar sind. Du gibst im Normalfall die Partie an. Das Programm probiert automatisch die konfigurierten Quellen, nutzt Cache-Dateien und lädt Elo-Ratings zuerst aus `data/elo_ratings.csv`, falls die Datei existiert. Wenn lokale Elo-Werte fehlen, wird automatisch eine Remote-Elo-Quelle abgefragt.

Für erwartete Gesamttore gilt: Wenn The Odds API einen `totals`-Markt liefert, wird daraus automatisch eine Torlinie abgeleitet. Andernfalls musst du `--total-goals` setzen.

```bash
python kicktipp_tool.py predict \
  --team-a "Argentina" \
  --team-b "France" \
  --total-goals 2.45
```

Für Quellen, die eine Tagesliste oder Fixture-Suche brauchen, gib zusätzlich das Spieldatum an:

```bash
python kicktipp_tool.py predict \
  --team-a "Argentina" \
  --team-b "France" \
  --match-date 2026-06-11 \
  --total-goals 2.45
```

Für frische API-Daten statt Cache:

```bash
python kicktipp_tool.py predict \
  --team-a "Argentina" \
  --team-b "France" \
  --match-date 2026-06-11 \
  --total-goals 2.45 \
  --refresh
```

## API-Keys

Kopiere `.env.example` nach `.env` und trage alle verfügbaren Keys ein:

```bash
cp .env.example .env
```

```dotenv
THE_ODDS_API_KEY=dein_key
FOOTBALL_DATA_API_KEY=dein_key
API_FOOTBALL_KEY=dein_key
```

Die automatische 1X2-Suche probiert standardmäßig:

1. The Odds API
2. football-data.org
3. API-Football predictions

Wenn eine Quelle nicht konfiguriert ist, keine Daten für die Partie findet oder weitere Angaben wie `--match-date` fehlen, wird die nächste Quelle probiert.

The Odds API wird mit `h2h,totals` abgefragt. `h2h` liefert die 1X2-Wahrscheinlichkeiten, `totals` liefert Over/Under-Linien für die automatische Gesamttor-Schätzung. Falls keine `totals` im Response enthalten sind, setze `--total-goals`.

## Manuelle Overrides

Du kannst 1X2-Wahrscheinlichkeiten und erwartete Gesamttore weiterhin direkt übergeben. Manuelle 1X2-Werte haben Vorrang vor allen APIs:

```bash
python kicktipp_tool.py predict \
  --team-a "Argentina" \
  --team-b "France" \
  --p-a 0.36 \
  --p-draw 0.29 \
  --p-b 0.35 \
  --total-goals 2.45 \
  --max-goals 6 \
  --tip-max-goals 5
```

Mit manuellem Elo:

```bash
python kicktipp_tool.py predict \
  --team-a "Argentina" \
  --team-b "France" \
  --p-a 0.36 \
  --p-draw 0.29 \
  --p-b 0.35 \
  --total-goals 2.45 \
  --elo-a 2113 \
  --elo-b 2081
```

## Quellen gezielt einschränken

Die API-Flags sind nicht mehr nötig. Sobald mindestens ein Quellen-Flag gesetzt ist, probiert das Tool nur diese ausgewählten Quellen.

Nur The Odds API:

```bash
python kicktipp_tool.py predict \
  --team-a "Argentina" \
  --team-b "France" \
  --use-odds-api \
  --odds-sport-key soccer_fifa_world_cup \
  --refresh
```

Der Default für `--odds-sport-key` ist `soccer_fifa_world_cup`. Für andere Wettbewerbe muss ein gültiger The-Odds-API-Sport-Key gesetzt werden, zum Beispiel `soccer_epl`. API-Antworten werden unter `cache/` gespeichert. Ohne `--refresh` versucht das Tool zuerst, den Cache zu verwenden.

football-data.org:

```bash
python kicktipp_tool.py predict \
  --team-a "Argentina" \
  --team-b "France" \
  --use-football-data \
  --football-data-match-id 123456 \
  --refresh
```

Alternativ kann `--match-date YYYY-MM-DD` genutzt werden, wenn die Partie ueber die Tagesliste gefunden werden soll.

API-Football:

```bash
python kicktipp_tool.py predict \
  --team-a "Argentina" \
  --team-b "France" \
  --use-api-football \
  --api-football-fixture-id 123456 \
  --refresh
```

Alternativ kann `--match-date YYYY-MM-DD` genutzt werden; dann sucht das Tool zuerst das passende Fixture und lädt danach die API-Football-Prognose.

## Elo-Ratings

Lege optional `data/elo_ratings.csv` an:

```csv
team,elo
Argentina,2113
France,2081
```

Danach:

```bash
python kicktipp_tool.py predict \
  --team-a "Argentina" \
  --team-b "France"
```

Elo wird standardmäßig geladen. Wenn ein Elo-Wert fehlt, läuft das Tool mit neutralem Elo weiter. Mit `--no-elo` deaktivierst du Elo gezielt.

Die Reihenfolge ist:

1. manuelle `--elo-a`/`--elo-b`
2. lokale `--elo-path` CSV, standardmäßig `data/elo_ratings.csv`
3. Remote-Elo, standardmäßig `international-football.net` für das aktuelle Datum

`international-football.net` veröffentlicht Nationalteam-Elo-Tabellen nach Datum und weist sie als von `eloratings.net` berechnet aus. Die Remote-Antwort wird unter `cache/` gespeichert; mit `--refresh` wird sie neu abgerufen.

Du kannst eine andere CSV- oder HTML-Quelle setzen, solange sie `team,elo`, `country,rating`, `club,elo` oder eine Rangliste im Format `1. Team 2139` enthält:

```bash
python kicktipp_tool.py predict \
  --team-a "Argentina" \
  --team-b "France" \
  --elo-url "https://www.international-football.net/elo-ratings-table?day=04&month=06&year=2026"
```

## Fixtures

`data_sources.load_fixtures_from_openfootball(path_or_url)` kann OpenFootball-JSON laden, lokal oder per URL. Die CLI ist bewusst auf die Tipp-Erzeugung fokussiert; Fixtures koennen als Adapter-Funktion in eigene Workflows eingebunden werden.

## Tests

Tests sind verpflichtend und liegen unter `tests/`.

```bash
pip install -r requirements.txt
pytest
```

## Dateien

- `kicktipp_tool.py`: CLI
- `models.py`: Poisson-Modell und Lambda-Herleitung
- `scoring.py`: Kicktipp-Punkte, EV und Ranking
- `data_sources.py`: Fixtures, Elo, Odds API, Cache
- `config.py`: `.env`-Konfiguration
