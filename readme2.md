Hier ist die umgewandelte Markdown-Version deiner Datei:

---

# Persoenlicher Gesundheitsberater

## Garmin + YAZIO + Claude AI

Installationsanleitung und Setup-Guide | Version 1.0 | März 2026 

---

### 1. Projektübersicht

Dieses Projekt kombiniert Bewegungsdaten von Garmin Connect mit Ernährungsdaten aus YAZIO und wertet sie mithilfe der Claude KI aus. Ziel ist ein persönlicher Gesundheitsberater, der langfristige Trends erkennt und individuelle Empfehlungen gibt.

| Datei | Beschreibung |
| --- | --- |
| `garmin_collector.py` | Lädt täglich Bewegungs-, Schlaf- und Aktivitätsdaten von Garmin Connect 

 |
| `yazio_connector.py` | Lädt täglich Ernährungsdaten (Kalorien, Makros) aus YAZIO 

 |
| `combined_view.py` | Verknüpft beide Datenquellen und bereitet den KI-Kontext auf 

 |
| `advisor_backend.py` | Lokaler Python-Webserver mit Claude API Anbindung 

 |
| `advisor_frontend.html` | Browser-Chat-Interface für den KI-Berater 

 |
| `garmin_auth.py` | Einmaliges interaktives Login bei Garmin (MFA-Unterstützung) 

 |
| `garmin_debug.py` | Hilfsskript zur Diagnose von Garmin-Profildaten 

 |
| `check_entries.py` | Zeigt YAZIO-Einträge eines Tages zur Kontrolle 

 |

---

### 2. Voraussetzungen

#### 2.1 Python installieren

1. Gehe zu [python.org/downloads](https://python.org/downloads).


2. Lade **Python 3.12** oder neuer herunter.


3. 
**Wichtig:** Setze den Haken bei **"Add Python to PATH"** beim Installer.


4. Überprüfe die Installation im Terminal mit: `py --version`.



#### 2.2 Python-Bibliotheken installieren

Öffne ein Terminal im Projektordner und führe aus:


`pip install garminconnect garth python-dotenv requests` 

#### 2.3 Anthropic API Key

1. Erstelle einen Account auf [console.anthropic.com](https://console.anthropic.com).


2. Erstelle unter "API Keys" einen neuen Schlüssel (beginnt mit `sk-ant-...`).


3. Trage ihn in die `.env` Datei ein.



---

### 3. Konfiguration (.env Datei)

Erstelle im Projektordner eine Datei namens `.env` mit folgendem Inhalt:

```env
# Garmin Connect Zugangsdaten
GARMIN_EMAIL=deine@email.de
GARMIN_PASSWORD=dein_garmin_passwort

# YAZIO Zugangsdaten
YAZIO_EMAIL=deine@email.de
YAZIO_PASSWORD=dein_yazio_passwort

# Anthropic API Key fuer den KI-Berater
ANTHROPIC_API_KEY=sk-ant-...

# Pfad zur Datenbank (Standard: garmin_data.db)
GARMIN_DB_PATH=garmin_data.db

```

> **Hinweis:** Die .env Datei niemals in ein Git-Repository einchecken! Sie enthält sensible Zugangsdaten.
> 
> 

---

### 4. Garmin Authentifizierung

Garmin verwendet eine Zwei-Faktor-Authentifizierung (MFA). Der Login muss einmalig interaktiv durchgeführt werden.

#### 4.1 Einmaliger Login

Führe das Skript `garmin_auth.py` aus und folge den Anweisungen (E-Mail, Passwort und ggf. Sicherheitscode eingeben).

#### 4.2 Token-Speicherort

| System | Pfad / Info |
| --- | --- |
| Windows | <br>`C:\Users\BENUTZERNAME\.garth\` 

 |
| macOS / Linux | <br>`~/.garth/` 

 |
| Gültigkeit | ca. 1 Jahr 

 |

---

### 5. YAZIO Authentifizierung

YAZIO verwendet eine inoffizielle API. Der Login erfolgt automatisch über die `.env` Daten.

#### 5.1 Wichtige API-Endpunkte

| Endpunkt | URL |
| --- | --- |
| Auth | <br>`https://yzapi.yazio.com/v20/oauth/token` 

 |
| Consumed Items | <br>`https://yzapi.yazio.com/v20/user/consumed-items` 

 |

---

### 6. Erster Sync (historische Daten)

Nach dem Setup können historische Daten geladen werden:

* 
**Garmin (letzte 30 Tage):** `py garmin_collector.py --days 30` 


* 
**YAZIO (letzte 30 Tage):** `py yazio_connector.py --days 30` 


* 
**Kombinierte Ansicht:** `py combined_view.py --days 14` 



---

### 7. Täglicher Sync

Für die tägliche Aktualisierung kannst du die Skripte manuell mit dem Parameter `--today` ausführen oder eine Aufgabe in der **Windows Aufgabenplanung** erstellen (z.B. täglich um 07:30 Uhr).

---

### 8. KI-Berater starten

1. 
**Backend starten:** `py advisor_backend.py` 


2. 
**Browser öffnen:** `http://localhost:8765` 


3. Das Backend muss während der Nutzung aktiv bleiben.



---

### 9. Datenbank einsehen

Alle Daten liegen in der SQLite-Datenbank `garmin_data.db`. Zur Ansicht wird der **DB Browser for SQLite** empfohlen.

| Tabelle | Inhalt |
| --- | --- |
| `daily_summary` | Schritte, Kalorien, Body Battery, Stress, SpO2 

 |
| `sleep` | Schlafdauer, Phasen, Schlaf-Score 

 |
| `yazio_daily` | Kalorien, Makros, Wasser pro Tag 

 |

---

### 10. Häufige Probleme

* **Garmin 403 Forbidden:** Token abgelaufen. `garmin_auth.py` neu ausführen.


* 
**Backend nicht erreichbar:** Prüfen, ob `advisor_backend.py` im Terminal läuft.


* 
**ANTHROPIC_API_KEY fehlt:** Key in der `.env` Datei kontrollieren.



---

Erstellt März 2026 | Garmin + YAZIO + Claude AI Gesundheitsberater