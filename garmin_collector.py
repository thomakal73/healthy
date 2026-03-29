"""
Garmin Connect Data Collector
==============================
Fetches daily health & activity data from Garmin Connect
and stores it in a local SQLite database.

Usage:
  python garmin_collector.py --today
  python garmin_collector.py --days 30
  python garmin_collector.py --from 2024-01-01 --to 2024-12-31
  python garmin_collector.py --export json
"""

import os
import json
import sqlite3
import argparse
import logging
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ── Logging (Windows-kompatibel, kein Unicode-Fehler) ─────────────────────────
import sys

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_stream = logging.StreamHandler(sys.stdout)
try:
    _stream.stream.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass  # Python < 3.7 fallback
_stream.setFormatter(_fmt)
_file = logging.FileHandler("garmin_collector.log", encoding="utf-8")
_file.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_stream, _file])
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
DB_PATH = Path(os.getenv("GARMIN_DB_PATH", "garmin_data.db"))
GARMIN_EMAIL = os.getenv("GARMIN_EMAIL", "")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD", "")


# ── Database ───────────────────────────────────────────────────────────────────
def init_db(conn: sqlite3.Connection):
    """Create all required tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            date            TEXT PRIMARY KEY,
            steps           INTEGER,
            distance_m      REAL,
            active_calories INTEGER,
            total_calories  INTEGER,
            floors_climbed  INTEGER,
            active_minutes  INTEGER,
            sedentary_minutes INTEGER,
            moderate_intensity_minutes INTEGER,
            vigorous_intensity_minutes INTEGER,
            body_battery_high INTEGER,
            body_battery_low  INTEGER,
            stress_avg        INTEGER,
            resting_hr        INTEGER,
            avg_spo2          REAL,
            hydration_ml      INTEGER,
            raw_json          TEXT,
            fetched_at        TEXT
        );

        CREATE TABLE IF NOT EXISTS sleep (
            date              TEXT PRIMARY KEY,
            sleep_start       TEXT,
            sleep_end         TEXT,
            total_sleep_sec   INTEGER,
            deep_sleep_sec    INTEGER,
            light_sleep_sec   INTEGER,
            rem_sleep_sec     INTEGER,
            awake_sec         INTEGER,
            sleep_score       INTEGER,
            avg_spo2          REAL,
            avg_respiration   REAL,
            raw_json          TEXT,
            fetched_at        TEXT
        );

        CREATE TABLE IF NOT EXISTS activities (
            activity_id       TEXT PRIMARY KEY,
            date              TEXT,
            name              TEXT,
            activity_type     TEXT,
            start_time        TEXT,
            duration_sec      INTEGER,
            distance_m        REAL,
            calories          INTEGER,
            avg_hr            INTEGER,
            max_hr            INTEGER,
            avg_pace_min_km   REAL,
            elevation_gain_m  REAL,
            steps             INTEGER,
            training_effect   REAL,
            aerobic_te        REAL,
            anaerobic_te      REAL,
            raw_json          TEXT,
            fetched_at        TEXT
        );

        CREATE TABLE IF NOT EXISTS heart_rate (
            date              TEXT PRIMARY KEY,
            resting_hr        INTEGER,
            min_hr            INTEGER,
            max_hr            INTEGER,
            raw_json          TEXT,
            fetched_at        TEXT
        );

        CREATE TABLE IF NOT EXISTS body_composition (
            date              TEXT PRIMARY KEY,
            weight_kg         REAL,
            bmi               REAL,
            body_fat_pct      REAL,
            muscle_mass_kg    REAL,
            bone_mass_kg      REAL,
            raw_json          TEXT,
            fetched_at        TEXT
        );

        CREATE TABLE IF NOT EXISTS training_status (
            date              TEXT PRIMARY KEY,
            training_readiness_score INTEGER,
            training_readiness_desc  TEXT,
            vo2max_running    REAL,
            vo2max_cycling    REAL,
            recovery_time_h   INTEGER,
            raw_json          TEXT,
            fetched_at        TEXT
        );
    """)
    conn.commit()
    log.info(f"Database ready: {DB_PATH}")


# ── Garmin Client ──────────────────────────────────────────────────────────────
def get_garmin_client():
    """Login via gespeichertem Token (~/.garth) oder frisch mit Credentials."""
    try:
        from garminconnect import Garmin
        import garth
    except ImportError:
        raise SystemExit("garminconnect/garth nicht installiert. Run: pip install garminconnect garth")

    token_path = os.getenv("GARTH_HOME", os.path.expanduser("~/.garth"))

    if os.path.exists(token_path):
        log.info("Token aus ~/.garth laden ...")
        client = Garmin()
        client.garth.load(token_path)
        # display_name aus garth.profile holen (enthaelt die korrekte UUID)
        try:
            client.display_name = client.garth.profile.get("displayName")
            log.info(f"display_name gesetzt: {client.display_name}")
        except Exception as e:
            log.warning(f"display_name konnte nicht gesetzt werden: {e}")
            client.display_name = None
    else:
        if not GARMIN_EMAIL or not GARMIN_PASSWORD:
            raise SystemExit(
                "Kein Token gefunden und keine Credentials in .env. "
                "Fuehre zuerst garmin_auth.py aus."
            )
        log.info(f"Logging in als {GARMIN_EMAIL} ...")
        client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
        client.login()
        client.garth.dump(token_path)

    log.info(f"Garmin Login OK (user: {client.display_name})")
    return client


# ── Fetch & Store Functions ────────────────────────────────────────────────────
def fetch_daily_summary(client, conn: sqlite3.Connection, day: date):
    """Fetch daily health stats and store them."""
    d = day.isoformat()
    try:
        stats = client.get_stats(d) or {}
        hr_data = client.get_heart_rates(d) or {}
        body_battery = client.get_body_battery(d) or []
        stress = client.get_stress_data(d) or {}
        hydration = client.get_hydration_data(d) or {}

        # Body battery: highest and lowest of the day
        bb_values = []
        for entry in body_battery:
            arr = entry.get("bodyBatteryValuesArray", [])
            for item in arr:
                if isinstance(item, list) and len(item) >= 2 and item[1] is not None:
                    bb_values.append(item[1])
        bb_high = max(bb_values) if bb_values else None
        bb_low = min(bb_values) if bb_values else None

        # Stress average
        stress_avg = stress.get("avgStressLevel")

        # Hydration in ml
        hydration_ml = hydration.get("totalIntakeInML")

        conn.execute("""
            INSERT OR REPLACE INTO daily_summary VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
        """, (
            d,
            stats.get("totalSteps"),
            stats.get("totalDistanceMeters"),
            stats.get("activeKilocalories"),
            stats.get("totalKilocalories"),
            stats.get("floorsAscended"),
            stats.get("userDurationMinutes"),
            stats.get("sedentaryMinutes"),
            stats.get("moderateIntensityMinutes"),
            stats.get("vigorousIntensityMinutes"),
            bb_high,
            bb_low,
            stress_avg,
            hr_data.get("restingHeartRate"),
            stats.get("averageSpo2"),
            hydration_ml,
            json.dumps({"stats": stats, "hr": hr_data, "stress": stress}),
            datetime.now().isoformat(),
        ))
        conn.commit()
        log.info(f"  ✅ Daily summary: {d} | Steps: {stats.get('totalSteps', '?')} | "
                 f"Calories: {stats.get('totalKilocalories', '?')} kcal")
    except Exception as e:
        log.warning(f"  ⚠️  Daily summary {d}: {e}")


def fetch_sleep(client, conn: sqlite3.Connection, day: date):
    """Fetch sleep data and store it."""
    d = day.isoformat()
    try:
        sleep = client.get_sleep_data(d) or {}
        sd = sleep.get("dailySleepDTO", {})

        conn.execute("""
            INSERT OR REPLACE INTO sleep VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?
            )
        """, (
            d,
            sd.get("sleepStartTimestampLocal"),
            sd.get("sleepEndTimestampLocal"),
            sd.get("sleepTimeSeconds"),
            sd.get("deepSleepSeconds"),
            sd.get("lightSleepSeconds"),
            sd.get("remSleepSeconds"),
            sd.get("awakeSleepSeconds"),
            sd.get("sleepScores", {}).get("overall", {}).get("value"),
            sd.get("averageSpO2Value"),
            sd.get("averageRespirationValue"),
            json.dumps(sleep),
            datetime.now().isoformat(),
        ))
        conn.commit()
        total_min = (sd.get("sleepTimeSeconds") or 0) // 60
        log.info(f"  ✅ Sleep: {d} | {total_min // 60}h {total_min % 60}min | "
                 f"Score: {sd.get('sleepScores', {}).get('overall', {}).get('value', '?')}")
    except Exception as e:
        log.warning(f"  ⚠️  Sleep {d}: {e}")


def fetch_activities(client, conn: sqlite3.Connection, start: date, end: date):
    """Fetch activities in a date range."""
    try:
        activities = client.get_activities_by_date(
            start.isoformat(), end.isoformat()
        ) or []
        count = 0
        for act in activities:
            act_id = str(act.get("activityId", ""))
            if not act_id:
                continue

            duration_sec = int(act.get("duration", 0))
            avg_pace = None
            dist = act.get("distance")
            if dist and duration_sec and dist > 0:
                avg_pace = (duration_sec / 60) / (dist / 1000)

            conn.execute("""
                INSERT OR REPLACE INTO activities VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
            """, (
                act_id,
                act.get("startTimeLocal", "")[:10],
                act.get("activityName"),
                act.get("activityType", {}).get("typeKey"),
                act.get("startTimeLocal"),
                duration_sec,
                dist,
                act.get("calories"),
                act.get("averageHR"),
                act.get("maxHR"),
                round(avg_pace, 2) if avg_pace else None,
                act.get("elevationGain"),
                act.get("steps"),
                act.get("trainingEffect"),
                act.get("aerobicTrainingEffect"),
                act.get("anaerobicTrainingEffect"),
                json.dumps(act),
                datetime.now().isoformat(),
            ))
            count += 1
        conn.commit()
        log.info(f"  ✅ Activities: {start} → {end} | {count} gespeichert")
    except Exception as e:
        log.warning(f"  ⚠️  Activities {start}→{end}: {e}")


def fetch_body_composition(client, conn: sqlite3.Connection, day: date):
    """Fetch body composition / weight data."""
    d = day.isoformat()
    try:
        data = client.get_body_composition(d) or {}
        rows = data.get("totalAverage", {})

        conn.execute("""
            INSERT OR REPLACE INTO body_composition VALUES (
                ?,?,?,?,?,?,?,?
            )
        """, (
            d,
            rows.get("weight") / 1000 if rows.get("weight") else None,  # g → kg
            rows.get("bmi"),
            rows.get("bodyFat"),
            rows.get("muscleMass") / 1000 if rows.get("muscleMass") else None,
            rows.get("boneMass") / 1000 if rows.get("boneMass") else None,
            json.dumps(data),
            datetime.now().isoformat(),
        ))
        conn.commit()
        weight = rows.get("weight")
        log.info(f"  ✅ Body comp: {d} | Gewicht: "
                 f"{weight / 1000:.1f} kg" if weight else f"  ✅ Body comp: {d} | keine Daten")
    except Exception as e:
        log.warning(f"  ⚠️  Body comp {d}: {e}")


def fetch_training_status(client, conn: sqlite3.Connection, day: date):
    """Fetch training readiness and VO2max."""
    d = day.isoformat()
    try:
        readiness = client.get_training_readiness(d) or {}
        # get_vo2max_summary existiert nicht in allen Versionen -> get_max_metrics nutzen
        try:
            vo2_raw = client.get_max_metrics(d) or {}
            vo2 = vo2_raw if isinstance(vo2_raw, dict) else {}
        except Exception:
            vo2 = {}

        score = None
        desc = None
        recovery_h = None
        if isinstance(readiness, list) and readiness:
            score = readiness[0].get("score")
            desc = readiness[0].get("levelDescription")
            recovery_h = readiness[0].get("recoveryTime")
        elif isinstance(readiness, dict):
            score = readiness.get("score")
            desc = readiness.get("levelDescription")
            recovery_h = readiness.get("recoveryTime")

        conn.execute("""
            INSERT OR REPLACE INTO training_status VALUES (
                ?,?,?,?,?,?,?,?
            )
        """, (
            d,
            score,
            desc,
            (vo2.get("generic", {}) or {}).get("vo2MaxPreciseValue") if isinstance(vo2, dict) else None,
            None,
            recovery_h,
            json.dumps({"readiness": readiness, "vo2": vo2}),
            datetime.now().isoformat(),
        ))
        conn.commit()
        log.info(f"  ✅ Training status: {d} | Readiness: {score} ({desc})")
    except Exception as e:
        log.warning(f"  ⚠️  Training status {d}: {e}")


# ── Export ─────────────────────────────────────────────────────────────────────
def export_json(conn: sqlite3.Connection, output_path: str = "garmin_export.json"):
    """Export all data as a single JSON file for the AI advisor."""
    tables = [
        "daily_summary", "sleep", "activities",
        "heart_rate", "body_composition", "training_status"
    ]
    export = {}
    for table in tables:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY date DESC").fetchall()
        cols = [d[0] for d in conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
        export[table] = [dict(zip(cols, row)) for row in rows]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)
    log.info(f"✅ Export gespeichert: {output_path}")


def print_summary(conn: sqlite3.Connection, days: int = 7):
    """Print a quick overview of recent data."""
    print("\n" + "═" * 60)
    print(f"  📊 Garmin Data – Letzte {days} Tage")
    print("═" * 60)

    rows = conn.execute(f"""
        SELECT date, steps, total_calories, resting_hr, body_battery_high, body_battery_low
        FROM daily_summary
        ORDER BY date DESC LIMIT {days}
    """).fetchall()

    print(f"  {'Datum':<12} {'Schritte':>8} {'Kal':>6} {'HR':>4} {'BB':>6}")
    print("  " + "-" * 42)
    for r in rows:
        bb = f"{r[5]}-{r[4]}" if r[4] and r[5] else "–"
        print(f"  {r[0]:<12} {str(r[1] or '–'):>8} {str(r[2] or '–'):>6} "
              f"{str(r[3] or '–'):>4} {bb:>6}")

    sleep_rows = conn.execute(f"""
        SELECT date, total_sleep_sec, sleep_score
        FROM sleep ORDER BY date DESC LIMIT {days}
    """).fetchall()

    print(f"\n  {'Datum':<12} {'Schlaf':>8} {'Score':>6}")
    print("  " + "-" * 30)
    for r in sleep_rows:
        mins = (r[1] or 0) // 60
        sleep_str = f"{mins // 60}h {mins % 60}min" if mins else "–"
        print(f"  {r[0]:<12} {sleep_str:>8} {str(r[2] or '–'):>6}")

    act_count = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    print(f"\n  🏃 Aktivitäten gesamt: {act_count}")
    print("═" * 60 + "\n")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Garmin Connect Data Collector")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--today", action="store_true", help="Nur heute")
    group.add_argument("--days", type=int, metavar="N", help="Letzte N Tage")
    group.add_argument("--from", dest="start", metavar="YYYY-MM-DD")
    parser.add_argument("--to", dest="end", metavar="YYYY-MM-DD",
                        default=date.today().isoformat())
    parser.add_argument("--export", choices=["json"], help="Exportformat")
    parser.add_argument("--summary", action="store_true", help="Übersicht anzeigen")
    args = parser.parse_args()

    # Determine date range
    if args.today:
        start_date = end_date = date.today()
    elif args.days:
        end_date = date.today()
        start_date = end_date - timedelta(days=args.days - 1)
    elif args.start:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
    else:
        start_date = end_date = date.today()

    # Init DB
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    if args.export == "json":
        export_json(conn)
        return

    if args.summary:
        print_summary(conn)
        return

    # Fetch data
    client = get_garmin_client()

    current = start_date
    while current <= end_date:
        log.info(f"\n📅 Verarbeite: {current.isoformat()}")
        fetch_daily_summary(client, conn, current)
        fetch_sleep(client, conn, current)
        fetch_body_composition(client, conn, current)
        fetch_training_status(client, conn, current)
        current += timedelta(days=1)

    # Activities in one batch (more efficient)
    fetch_activities(client, conn, start_date, end_date)

    print_summary(conn, days=min(7, (end_date - start_date).days + 1))
    log.info("✅ Fertig!")
    conn.close()


if __name__ == "__main__":
    main()
