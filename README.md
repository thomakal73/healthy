# 🏃 Garmin Data Collector

Fetcht täglich deine Garmin-Connect-Daten und speichert sie lokal in SQLite.

## Setup

```bash
# 1. Abhängigkeiten installieren
pip install -r requirements.txt

# 2. .env anlegen
cp .env.example .env
# → .env öffnen und Garmin-Zugangsdaten eintragen

# 3. Test: Heutigen Tag holen
python garmin_collector.py --today

# 4. Historische Daten nachladen (z.B. letzte 90 Tage)
python garmin_collector.py --days 90
```

## Verwendung

```bash
# Nur heute
python garmin_collector.py --today

# Letzte 30 Tage
python garmin_collector.py --days 30

# Bestimmten Zeitraum
python garmin_collector.py --from 2024-01-01 --to 2024-12-31

# Übersicht der gespeicherten Daten anzeigen
python garmin_collector.py --summary

# Als JSON exportieren (für KI-Berater)
python garmin_collector.py --export json
```

## Automatischer täglicher Sync (Cron)

```bash
# Crontab öffnen
crontab -e

# Täglich um 07:00 Uhr holen
0 7 * * * cd /pfad/zum/projekt && python garmin_collector.py --today >> cron.log 2>&1
```

## Gespeicherte Daten

| Tabelle | Inhalt |
|---|---|
| `daily_summary` | Schritte, Kalorien, Body Battery, Stress, SpO2 |
| `sleep` | Schlafdauer, Tiefschlaf, REM, Schlaf-Score |
| `activities` | Workouts mit Distanz, Pace, HR, Kalorien |
| `body_composition` | Gewicht, BMI, Körperfettanteil |
| `training_status` | Training Readiness, VO2max, Erholungszeit |

## Datenbankstruktur (SQLite)

```
garmin_data.db
├── daily_summary      ← Haupttabelle: tägliche Zusammenfassung
├── sleep              ← Schlafanalyse
├── activities         ← Alle Aktivitäten/Workouts
├── heart_rate         ← Herzfrequenz
├── body_composition   ← Körperzusammensetzung
└── training_status    ← Trainingsbereitschaft & VO2max
```

## Nächste Schritte

- `garmin_data.db` mit YAZIO-Daten verbinden
- KI-Berater mit Claude API bauen
- Dashboard mit Grafiken erstellen
