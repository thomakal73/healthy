# 🫀 Persönlicher Gesundheitsberater
### Garmin + YAZIO + Claude AI

Kombiniert Bewegungsdaten von Garmin Connect mit Ernährungsdaten aus YAZIO und wertet sie mithilfe der Claude KI aus. Ziel ist ein persönlicher Gesundheitsberater der langfristige Trends erkennt und individuelle Empfehlungen gibt.

---

## Projektstruktur

```
projekt/
  garmin_collector.py      # Garmin Daten-Collector
  yazio_connector.py       # YAZIO Daten-Connector
  combined_view.py         # Kombinierte Auswertung
  advisor_backend.py       # KI-Berater Backend (lokaler Webserver)
  advisor_frontend.html    # KI-Berater Browser-UI
  garmin_auth.py           # Garmin Login (einmalig, MFA)
  check_entries.py         # YAZIO Debug-Hilfe
  garmin_debug.py          # Garmin Debug-Hilfe
  .env                     # Zugangsdaten (NICHT in Git!)
  garmin_data.db           # SQLite Datenbank (wird automatisch erstellt)
  .yazio_token.json        # YAZIO Token-Cache (wird automatisch erstellt)
```

---

## 1. Voraussetzungen

### Python installieren

1. Download: https://python.org/downloads (Python 3.12 oder neuer)
2. **Wichtig:** Beim Installer den Haken bei **"Add Python to PATH"** setzen
3. Installation prüfen:
```bash
py --version
```

### Python-Bibliotheken installieren

```bash
pip install garminconnect garth python-dotenv requests
```

---

## 2. Konfiguration (.env)

Erstelle im Projektordner eine Datei namens `.env`:

```env
# Garmin Connect Zugangsdaten
GARMIN_EMAIL=deine@email.de
GARMIN_PASSWORD=dein_garmin_passwort

# YAZIO Zugangsdaten
YAZIO_EMAIL=deine@email.de
YAZIO_PASSWORD=dein_yazio_passwort

# Anthropic API Key für den KI-Berater
# Erstellen auf: https://console.anthropic.com → API Keys
ANTHROPIC_API_KEY=sk-ant-...

# Pfad zur Datenbank (Standard: garmin_data.db im Projektordner)
GARMIN_DB_PATH=garmin_data.db
```

> ⚠️ Die `.env` Datei niemals in ein Git-Repository einchecken!

---

## 3. Garmin Authentifizierung

Garmin verwendet Zwei-Faktor-Authentifizierung. Der Login muss **einmalig interaktiv** durchgeführt werden. Das Token wird danach für ca. ein Jahr gespeichert.

### Einmaliger Login

Erstelle die Datei `garmin_auth.py`:

```python
import garth
from getpass import getpass

email    = input("Garmin E-Mail: ")
password = getpass("Passwort: ")

garth.login(email, password)
garth.save("~/.garth")
print("Token gespeichert!")
```

Ausführen:
```bash
py garmin_auth.py
```

1. E-Mail und Passwort eingeben
2. Sicherheitscode aus der Garmin-E-Mail eingeben
3. Token wird gespeichert unter:
   - **Windows:** `C:\Users\BENUTZERNAME\.garth\`
   - **macOS/Linux:** `~/.garth/`

### Token erneuern

Wenn der Token abläuft (nach ~1 Jahr) oder ein 403-Fehler auftritt:
```bash
py garmin_auth.py
```

---

## 4. YAZIO Authentifizierung

YAZIO verwendet eine inoffizielle API. Der Login erfolgt **automatisch** über die `.env` Zugangsdaten — kein manueller Schritt nötig.

Der Token wird automatisch in `.yazio_token.json` gecacht und bei Ablauf erneuert.

| Endpunkt | URL |
|---|---|
| Auth | `https://yzapi.yazio.com/v20/oauth/token` |
| Consumed Items | `https://yzapi.yazio.com/v20/user/consumed-items` |
| Produktdaten | `https://yzapi.yazio.com/v20/products/{id}` |
| Rezeptdaten | `https://yzapi.yazio.com/v20/recipes/{id}` |

> ⚠️ Die YAZIO-API ist nicht offiziell dokumentiert und kann sich ändern.

---

## 5. Erster Sync (historische Daten)

```bash
# Garmin: letzte 30 Tage laden
py garmin_collector.py --days 30

# YAZIO: letzte 30 Tage laden
py yazio_connector.py --days 30

# Daten prüfen
py garmin_collector.py --summary
py yazio_connector.py --summary
py combined_view.py --days 14
```

---

## 6. Täglicher Sync

### Manuell

```bash
py garmin_collector.py --today
py yazio_connector.py --today
```

### Automatisch (Windows Aufgabenplanung)

1. Windows-Taste → "Aufgabenplanung" öffnen
2. "Aufgabe erstellen" → Trigger: Täglich 07:30 Uhr
3. Aktion: `py C:\pfad\zum\projekt\garmin_collector.py --today`
4. Zweite Aufgabe analog für `yazio_connector.py`

---

## 7. KI-Berater starten

```bash
# Backend starten
py advisor_backend.py

# Browser öffnen
http://localhost:8765
```

> Das Backend muss laufen solange du den Berater verwendest. Beenden mit `Ctrl+C`.

Der Berater analysiert die letzten 30 Tage (einstellbar: 7/14/30/60 Tage) und erkennt Trends in Ernährung, Schlaf, Body Battery und Aktivität.

---

## 8. Datenbank einsehen

Alle Daten liegen in `garmin_data.db` (SQLite).

**DB Browser for SQLite** (empfohlen): https://sqlitebrowser.org/dl/
→ `garmin_data.db` per Drag & Drop öffnen

| Tabelle | Inhalt |
|---|---|
| `daily_summary` | Garmin: Schritte, Kalorien, Body Battery, Stress, SpO2 |
| `sleep` | Garmin: Schlafdauer, Tiefschlaf, REM, Schlaf-Score |
| `activities` | Garmin: Workouts mit Distanz, Pace, Herzrate |
| `body_composition` | Garmin: Gewicht, BMI, Körperfettanteil |
| `training_status` | Garmin: Training Readiness, VO2max, Erholungszeit |
| `yazio_daily` | YAZIO: Kalorien, Makros, Wasser pro Tag |
| `yazio_entries` | YAZIO: Einzelne Lebensmitteleinträge mit Nährwerten |
| `yazio_weight` | YAZIO: Gewichtsverlauf |

---

## 9. Alle Befehle im Überblick

```bash
# Garmin
py garmin_collector.py --today
py garmin_collector.py --days 30
py garmin_collector.py --from 2026-01-01 --to 2026-03-11
py garmin_collector.py --summary
py garmin_collector.py --export json

# YAZIO
py yazio_connector.py --today
py yazio_connector.py --days 30
py yazio_connector.py --summary

# Kombiniert
py combined_view.py --days 14
py combined_view.py --export json
py combined_view.py --export context

# KI-Berater
py advisor_backend.py            # Starten → http://localhost:8765

# Debug
py garmin_debug.py               # Garmin Profil anzeigen
py check_entries.py              # YAZIO Einträge prüfen
```

---

## 10. Häufige Probleme

| Problem | Lösung |
|---|---|
| `403 Forbidden` (Garmin) | Token abgelaufen → `py garmin_auth.py` erneut ausführen |
| `display_name = None` | Token-Profil fehlerhaft → `py garmin_auth.py` erneut ausführen |
| YAZIO Login fehlgeschlagen | Zugangsdaten in `.env` prüfen |
| YAZIO `404` auf Endpunkt | API-Version geändert → Netzwerkmitschnitt in YAZIO App prüfen |
| Backend nicht erreichbar | `py advisor_backend.py` muss im Terminal laufen |
| `ANTHROPIC_API_KEY fehlt` | Key in `.env` eintragen (console.anthropic.com) |
| `UnicodeEncodeError` | Aktuelle Dateiversion verwenden (UTF-8 Logging) |

---

*Erstellt März 2026 · Garmin + YAZIO + Claude AI*
