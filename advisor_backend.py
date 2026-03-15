"""
Gesundheitsberater Backend
===========================
Lokaler HTTP-Server der die Garmin+YAZIO DB liest und
Chat-Anfragen an Claude weiterleitet.

Start: py advisor_backend.py
Dann: http://localhost:8765
"""

import json
import sqlite3
import os
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DB_PATH      = Path(os.getenv("GARMIN_DB_PATH", "garmin_data.db"))
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PORT          = 8765
HISTORY_DAYS  = 30


# ── Daten aus DB laden ─────────────────────────────────────────────────────────
def load_combined_data(days: int = HISTORY_DAYS) -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT
                COALESCE(g.date, y.date)             AS date,
                y.calories_eaten                      AS kcal_eaten,
                y.protein_g, y.carbs_g, y.fat_g,
                y.fiber_g, y.water_ml,
                y.breakfast_kcal, y.lunch_kcal,
                y.dinner_kcal, y.snacks_kcal,
                g.steps,
                g.active_calories                     AS kcal_burned,
                g.active_minutes,
                g.moderate_intensity_minutes,
                g.vigorous_intensity_minutes,
                g.resting_hr,
                g.body_battery_high,
                g.body_battery_low,
                g.stress_avg,
                s.total_sleep_sec / 3600.0            AS sleep_hours,
                s.deep_sleep_sec  / 3600.0            AS deep_sleep_hours,
                s.rem_sleep_sec   / 3600.0            AS rem_sleep_hours,
                s.sleep_score,
                COALESCE(w.weight_kg, bc.weight_kg)   AS weight_kg,
                bc.body_fat_pct,
                ts.training_readiness_score,
                ts.vo2max_running,
                ts.recovery_time_h,
                CASE
                  WHEN y.calories_eaten IS NOT NULL AND g.active_calories IS NOT NULL
                  THEN y.calories_eaten - g.active_calories
                  ELSE NULL
                END AS calorie_balance
            FROM daily_summary g
            FULL OUTER JOIN yazio_daily y   ON g.date = y.date
            LEFT JOIN sleep s               ON COALESCE(g.date, y.date) = s.date
            LEFT JOIN yazio_weight w        ON COALESCE(g.date, y.date) = w.date
            LEFT JOIN body_composition bc   ON COALESCE(g.date, y.date) = bc.date
            LEFT JOIN training_status ts    ON COALESCE(g.date, y.date) = ts.date
            WHERE COALESCE(g.date, y.date) >= date('now', ?)
            ORDER BY date DESC
        """, (f"-{days} days",)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"DB error: {e}")
        return []
    finally:
        conn.close()


def load_top_foods(days: int = HISTORY_DAYS) -> list[dict]:
    """Häufigste Lebensmittel der letzten N Tage."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT food_name, COUNT(*) as freq,
                   ROUND(AVG(calories), 1) as avg_kcal,
                   ROUND(AVG(protein_g), 1) as avg_protein
            FROM yazio_entries
            WHERE date >= date('now', ?)
              AND food_name IS NOT NULL
            GROUP BY food_name
            ORDER BY freq DESC
            LIMIT 15
        """, (f"-{days} days",)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def build_context(days: int = HISTORY_DAYS) -> str:
    """Kompakter Kontext-String für Claude."""
    data = load_combined_data(days)
    foods = load_top_foods(days)

    if not data:
        return "Keine Daten in der Datenbank verfügbar."

    # Nutzerinfo aus DB
    lines = [
        f"# Gesundheitsdaten Thomas Kalinna – Letzte {days} Tage\n",
        f"Analysezeitraum: {data[-1]['date']} bis {data[0]['date']}",
        f"Verfügbare Tage: {len(data)}\n",
    ]

    # Durchschnitte berechnen
    def avg(key):
        vals = [r[key] for r in data if r.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def trend(key):
        """Vergleicht erste und zweite Hälfte des Zeitraums."""
        vals = [(r['date'], r[key]) for r in data if r.get(key) is not None]
        if len(vals) < 6:
            return None
        vals.sort(key=lambda x: x[0])
        mid = len(vals) // 2
        first_half = sum(v for _, v in vals[:mid]) / mid
        second_half = sum(v for _, v in vals[mid:]) / (len(vals) - mid)
        diff = second_half - first_half
        return round(diff, 1)

    lines.append("## Durchschnittswerte")
    lines.append(f"- Kalorien:      {avg('kcal_eaten')} kcal/Tag")
    lines.append(f"- Protein:       {avg('protein_g')}g/Tag")
    lines.append(f"- Kohlenhydrate: {avg('carbs_g')}g/Tag")
    lines.append(f"- Fett:          {avg('fat_g')}g/Tag")
    lines.append(f"- Schritte:      {avg('steps')}/Tag")
    lines.append(f"- Aktive Minuten:{avg('active_minutes')} min/Tag")
    lines.append(f"- Schlaf:        {avg('sleep_hours')}h/Nacht")
    lines.append(f"- Schlaf-Score:  {avg('sleep_score')}/100")
    lines.append(f"- Ruhepuls:      {avg('resting_hr')} bpm")
    lines.append(f"- Body Battery:  {avg('body_battery_low')}-{avg('body_battery_high')}")
    lines.append(f"- Stress:        {avg('stress_avg')}/100")
    if avg('weight_kg'):
        lines.append(f"- Gewicht:       {avg('weight_kg')} kg")
    lines.append("")

    # Trends
    lines.append("## Trends (Vergleich 1. vs 2. Hälfte des Zeitraums)")
    for key, label, unit in [
        ('kcal_eaten', 'Kalorien', 'kcal'),
        ('protein_g', 'Protein', 'g'),
        ('steps', 'Schritte', ''),
        ('sleep_hours', 'Schlaf', 'h'),
        ('sleep_score', 'Schlaf-Score', ''),
        ('weight_kg', 'Gewicht', 'kg'),
        ('stress_avg', 'Stress', ''),
    ]:
        t = trend(key)
        if t is not None:
            arrow = "↑" if t > 0 else "↓" if t < 0 else "→"
            lines.append(f"- {label}: {arrow} {abs(t)}{unit}")
    lines.append("")

    # Tagesdaten Tabelle
    lines.append("## Tagesdaten (neueste zuerst)")
    lines.append("Datum       | Kcal | Prot | Carb | Fett | Schritte | Schlaf | Score | HR  | BB    | Stress")
    lines.append("-" * 100)
    for r in data:
        bb = f"{r['body_battery_low'] or '?'}-{r['body_battery_high'] or '?'}" if r.get('body_battery_high') else "–"
        sleep = f"{round(r['sleep_hours'], 1)}h" if r.get('sleep_hours') else "–"
        lines.append(
            f"{r['date']} | "
            f"{str(round(r['kcal_eaten'] or 0)):>4} | "
            f"{str(round(r['protein_g'] or 0)):>4} | "
            f"{str(round(r['carbs_g'] or 0)):>4} | "
            f"{str(round(r['fat_g'] or 0)):>4} | "
            f"{str(r['steps'] or '–'):>8} | "
            f"{sleep:>6} | "
            f"{str(r['sleep_score'] or '–'):>5} | "
            f"{str(r['resting_hr'] or '–'):>3} | "
            f"{bb:>5} | "
            f"{str(r['stress_avg'] or '–'):>6}"
        )
    lines.append("")

    # Häufigste Lebensmittel
    if foods:
        lines.append("## Häufig gegessene Lebensmittel")
        for f in foods:
            lines.append(f"- {f['food_name']} ({f['freq']}x, ~{f['avg_kcal']} kcal, ~{f['avg_protein']}g Protein)")

    return "\n".join(lines)


SYSTEM_PROMPT = """Du bist ein persönlicher Gesundheits- und Ernährungsberater für Thomas Kalinna (52 Jahre, männlich, 173cm, ~98kg).

Du analysierst seine kombinierten Garmin-Bewegungs- und YAZIO-Ernährungsdaten der letzten 30 Tage.

Deine Aufgaben:
- Erkenne Muster und Entwicklungen über Zeit (nicht nur einzelne Tage)
- Verbinde Ernährung mit Schlaf, Energie (Body Battery), Stress und Aktivität
- Gib konkrete, personalisierte Empfehlungen basierend auf seinen echten Daten
- Sei direkt und ehrlich, aber motivierend
- Antworte auf Deutsch
- Nutze die Daten aktiv in deinen Antworten (nenne konkrete Zahlen)

Wichtig: Du hast Zugang zu echten Gesundheitsdaten. Nutze sie für präzise, individuelle Aussagen statt allgemeiner Ratschläge."""


# ── HTTP Handler ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Kein HTTP-Log-Spam

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_GET(self):
        if self.path == "/":
            self._serve_file("advisor_frontend.html", "text/html")
        elif self.path == "/context":
            ctx = build_context()
            self._json({"context": ctx, "days": len(load_combined_data())})
        elif self.path == "/status":
            data = load_combined_data(7)
            self._json({
                "db_exists": DB_PATH.exists(),
                "days_available": len(load_combined_data()),
                "api_key_set": bool(ANTHROPIC_KEY),
                "latest_date": data[0]["date"] if data else None,
            })
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/chat":
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length))
            messages  = body.get("messages", [])
            days      = body.get("days", HISTORY_DAYS)

            if not ANTHROPIC_KEY:
                self._json({"error": "ANTHROPIC_API_KEY fehlt in .env"}, 500)
                return

            context = build_context(days)

            # Kontext als erstes User-Message injizieren
            full_messages = [
                {"role": "user",      "content": f"Hier sind meine aktuellen Gesundheitsdaten:\n\n{context}"},
                {"role": "assistant", "content": "Ich habe deine Daten geladen und analysiert. Was möchtest du wissen?"},
            ] + messages

            try:
                req_body = json.dumps({
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1500,
                    "system": SYSTEM_PROMPT,
                    "messages": full_messages,
                }).encode()

                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    data=req_body,
                    headers={
                        "x-api-key": ANTHROPIC_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read())
                    reply = result["content"][0]["text"]
                    self._json({"reply": reply})

            except urllib.error.HTTPError as e:
                err = e.read().decode()
                self._json({"error": f"Claude API Fehler: {err}"}, 500)
            except Exception as e:
                self._json({"error": str(e)}, 500)

    def _serve_file(self, filename, content_type):
        path = Path(filename)
        if not path.exists():
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self._cors()
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if not ANTHROPIC_KEY:
        print("WARNUNG: ANTHROPIC_API_KEY nicht in .env gesetzt!")
        print("Trage deinen API-Key in die .env Datei ein:")
        print("  ANTHROPIC_API_KEY=sk-ant-...")
        print()

    print(f"Gesundheitsberater gestartet: http://localhost:{PORT}")
    print(f"Datenbank: {DB_PATH} ({'gefunden' if DB_PATH.exists() else 'NICHT GEFUNDEN'})")
    print("Beenden: Ctrl+C")
    HTTPServer(("localhost", PORT), Handler).serve_forever()
