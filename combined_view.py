"""
Combined View: Garmin + YAZIO
==============================
Erstellt eine kombinierte Tagesansicht aus beiden Datenquellen.
Kann als Grundlage für den KI-Berater verwendet werden.

Usage:
  python combined_view.py --days 30
  python combined_view.py --date 2024-11-15
  python combined_view.py --export json
"""

import sqlite3
import json
import argparse
from datetime import date, timedelta
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()
DB_PATH = Path(os.getenv("GARMIN_DB_PATH", "garmin_data.db"))


COMBINED_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS daily_combined AS
SELECT
    -- Datum (gemeinsamer Key)
    COALESCE(g.date, y.date)            AS date,

    -- ── Ernährung (YAZIO) ──────────────────────────────────────
    y.calories_eaten                     AS kcal_eaten,
    y.calories_goal                      AS kcal_goal,
    ROUND(y.calories_eaten * 1.0 / NULLIF(y.calories_goal, 0) * 100, 1) AS kcal_goal_pct,
    y.protein_g,
    y.carbs_g,
    y.fat_g,
    y.fiber_g,
    y.water_ml,
    y.breakfast_kcal,
    y.lunch_kcal,
    y.dinner_kcal,
    y.snacks_kcal,

    -- ── Aktivität (Garmin) ─────────────────────────────────────
    g.steps,
    g.active_calories                    AS kcal_burned_garmin,
    g.total_calories                     AS kcal_total_garmin,
    g.active_minutes,
    g.moderate_intensity_minutes,
    g.vigorous_intensity_minutes,
    g.floors_climbed,
    g.resting_hr,
    g.body_battery_high,
    g.body_battery_low,
    g.stress_avg,

    -- ── Schlaf (Garmin) ────────────────────────────────────────
    s.total_sleep_sec / 3600.0           AS sleep_hours,
    s.deep_sleep_sec / 3600.0           AS deep_sleep_hours,
    s.rem_sleep_sec / 3600.0            AS rem_sleep_hours,
    s.sleep_score,

    -- ── Körper ────────────────────────────────────────────────
    COALESCE(w.weight_kg, bc.weight_kg) AS weight_kg,
    bc.body_fat_pct,

    -- ── Training ──────────────────────────────────────────────
    ts.training_readiness_score,
    ts.vo2max_running,
    ts.recovery_time_h,

    -- ── Kalorien-Bilanz ────────────────────────────────────────
    CASE
      WHEN y.calories_eaten IS NOT NULL AND g.active_calories IS NOT NULL
      THEN y.calories_eaten - g.active_calories
    END AS calorie_balance

FROM garmin.daily_summary g
FULL OUTER JOIN yazio_daily y    ON g.date = y.date
LEFT JOIN garmin.sleep s         ON g.date = s.date
LEFT JOIN yazio_weight w         ON g.date = w.date
LEFT JOIN garmin.body_composition bc ON g.date = bc.date
LEFT JOIN garmin.training_status ts  ON g.date = ts.date
ORDER BY date DESC;
"""


def get_combined_data(conn: sqlite3.Connection, days: int = 30) -> list[dict]:
    """
    Returns combined Garmin + YAZIO data for the last N days.
    Works without the view by using inline SQL.
    """
    sql = """
    SELECT
        COALESCE(g.date, y.date)            AS date,
        y.calories_eaten                     AS kcal_eaten,
        y.calories_goal                      AS kcal_goal,
        y.protein_g, y.carbs_g, y.fat_g,
        y.fiber_g, y.water_ml,
        y.breakfast_kcal, y.lunch_kcal,
        y.dinner_kcal, y.snacks_kcal,
        g.steps,
        g.active_calories                    AS kcal_burned,
        g.active_minutes,
        g.moderate_intensity_minutes,
        g.vigorous_intensity_minutes,
        g.resting_hr,
        g.body_battery_high,
        g.body_battery_low,
        g.stress_avg,
        s.total_sleep_sec / 3600.0           AS sleep_hours,
        s.deep_sleep_sec / 3600.0            AS deep_sleep_hours,
        s.rem_sleep_sec / 3600.0             AS rem_sleep_hours,
        s.sleep_score,
        COALESCE(w.weight_kg, bc.weight_kg)  AS weight_kg,
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
    FULL OUTER JOIN yazio_daily y    ON g.date = y.date
    LEFT JOIN sleep s                ON COALESCE(g.date, y.date) = s.date
    LEFT JOIN yazio_weight w         ON COALESCE(g.date, y.date) = w.date
    LEFT JOIN body_composition bc    ON COALESCE(g.date, y.date) = bc.date
    LEFT JOIN training_status ts     ON COALESCE(g.date, y.date) = ts.date
    WHERE COALESCE(g.date, y.date) >= date('now', ?)
    ORDER BY date DESC
    """
    offset = f"-{days} days"
    rows = conn.execute(sql, (offset,)).fetchall()
    cols = [d[0] for d in conn.execute(sql + " LIMIT 0", (offset,)).description
            ] if False else [
        "date", "kcal_eaten", "kcal_goal", "protein_g", "carbs_g", "fat_g",
        "fiber_g", "water_ml", "breakfast_kcal", "lunch_kcal", "dinner_kcal",
        "snacks_kcal", "steps", "kcal_burned", "active_minutes",
        "moderate_intensity_minutes", "vigorous_intensity_minutes",
        "resting_hr", "body_battery_high", "body_battery_low", "stress_avg",
        "sleep_hours", "deep_sleep_hours", "rem_sleep_hours", "sleep_score",
        "weight_kg", "body_fat_pct", "training_readiness_score",
        "vo2max_running", "recovery_time_h", "calorie_balance"
    ]
    return [dict(zip(cols, row)) for row in rows]


def build_ai_context(conn: sqlite3.Connection, days: int = 14) -> str:
    """
    Build a compact context string for the AI advisor.
    Designed to fit in a Claude prompt.
    """
    data = get_combined_data(conn, days)

    if not data:
        return "Keine Daten verfügbar."

    lines = [
        f"Gesundheitsdaten der letzten {days} Tage (neueste zuerst):\n",
        f"{'Datum':<12} {'Kcal':>5} {'Ziel':>5} {'P':>4} {'C':>4} {'F':>4} "
        f"{'H2O':>5} {'Kcal↑':>5} {'Schritte':>8} {'Schlaf':>6} {'BB':>4} {'Stress':>6} {'Gewicht':>7}",
        "-" * 100,
    ]
    for d in data:
        water = f"{d['water_ml']}ml" if d['water_ml'] else "–"
        bb    = f"{d['body_battery_low'] or '?'}-{d['body_battery_high'] or '?'}" if d['body_battery_high'] else "–"
        sleep = f"{round(d['sleep_hours'], 1)}h" if d['sleep_hours'] else "–"
        lines.append(
            f"{d['date']:<12} "
            f"{str(round(d['kcal_eaten'] or 0)):>5} "
            f"{str(d['kcal_goal'] or '–'):>5} "
            f"{str(round(d['protein_g'] or 0)):>4} "
            f"{str(round(d['carbs_g'] or 0)):>4} "
            f"{str(round(d['fat_g'] or 0)):>4} "
            f"{water:>5} "
            f"{str(round(d['kcal_burned'] or 0)):>5} "
            f"{str(d['steps'] or '–'):>8} "
            f"{sleep:>6} "
            f"{bb:>4} "
            f"{str(d['stress_avg'] or '–'):>6} "
            f"{(str(round(d['weight_kg'], 1)) + 'kg') if d['weight_kg'] else '–':>7}"
        )

    # Averages
    def avg(key):
        vals = [d[key] for d in data if d[key] is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    lines += [
        "",
        f"Durchschnitte ({days}d): "
        f"Kcal {avg('kcal_eaten')} | "
        f"Protein {avg('protein_g')}g | "
        f"Schritte {avg('steps')} | "
        f"Schlaf {avg('sleep_hours')}h | "
        f"Gewicht {avg('weight_kg')}kg",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Combined Garmin + YAZIO View")
    parser.add_argument("--days",   type=int, default=14)
    parser.add_argument("--date",   help="Einzelner Tag YYYY-MM-DD")
    parser.add_argument("--export", choices=["json", "context"])
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)

    if args.export == "json":
        data = get_combined_data(conn, args.days)
        out  = "combined_data.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ Exportiert: {out} ({len(data)} Tage)")

    elif args.export == "context":
        ctx = build_ai_context(conn, args.days)
        out = "ai_context.txt"
        with open(out, "w", encoding="utf-8") as f:
            f.write(ctx)
        print(f"✅ KI-Kontext exportiert: {out}")

    else:
        ctx = build_ai_context(conn, args.days)
        print(ctx)

    conn.close()


if __name__ == "__main__":
    main()
