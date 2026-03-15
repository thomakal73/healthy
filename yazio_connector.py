"""
YAZIO Data Connector
=====================
Fetches daily nutrition data from YAZIO (unofficial API)
and stores it in the same SQLite database as the Garmin Collector.

Usage:
  python yazio_connector.py --today
  python yazio_connector.py --days 30
  python yazio_connector.py --from 2024-01-01 --to 2024-12-31
  python yazio_connector.py --summary
  python yazio_connector.py --export json
"""

import os
import json
import sqlite3
import argparse
import logging
import time
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Optional
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Logging (Windows-kompatibel, kein Unicode-Fehler) ─────────────────────────
import sys
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_stream = logging.StreamHandler(sys.stdout)
try:
    _stream.stream.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
_stream.setFormatter(_fmt)
_file = logging.FileHandler("yazio_connector.log", encoding="utf-8")
_file.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_stream, _file])
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
DB_PATH        = Path(os.getenv("GARMIN_DB_PATH", "garmin_data.db"))  # same DB!
YAZIO_EMAIL    = os.getenv("YAZIO_EMAIL", "")
YAZIO_PASSWORD = os.getenv("YAZIO_PASSWORD", "")

# YAZIO API base URLs (reverse-engineered, may change)
API_BASE    = "https://yzapi.yazio.com"
AUTH_URL    = f"{API_BASE}/v20/oauth/token"
DIARY_URL   = f"{API_BASE}/v20/user/consumed-items"
SUMMARY_URL = f"{API_BASE}/v20/users/me/diary-summaries"
WEIGHT_URL  = f"{API_BASE}/v20/users/me/body-measurements"
WATER_URL   = f"{API_BASE}/v20/users/me/water-entries"
GOALS_URL   = f"{API_BASE}/v20/users/me/goals"
PROFILE_URL = f"{API_BASE}/v7/users/me"

CLIENT_ID     = "3_5rbw4kehpugw8ogsc8ck8oo4ogswgckcskc04gcg8kk8k48ssw"
CLIENT_SECRET = "25gdtt1hvdi8gwowoww4oo88sgsw0oo04o0og0kkgwwks8k0k"

TOKEN_CACHE_FILE = Path(".yazio_token.json")


# ── Database ───────────────────────────────────────────────────────────────────
def init_db(conn: sqlite3.Connection):
    """Create YAZIO tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS yazio_daily (
            date                TEXT PRIMARY KEY,
            calories_goal       INTEGER,
            calories_eaten      INTEGER,
            calories_burned     INTEGER,   -- from YAZIO activity tracking
            calories_net        INTEGER,
            protein_g           REAL,
            carbs_g             REAL,
            fat_g               REAL,
            fiber_g             REAL,
            sugar_g             REAL,
            sodium_mg           REAL,
            water_ml            INTEGER,
            breakfast_kcal      INTEGER,
            lunch_kcal          INTEGER,
            dinner_kcal         INTEGER,
            snacks_kcal         INTEGER,
            raw_json            TEXT,
            fetched_at          TEXT
        );

        CREATE TABLE IF NOT EXISTS yazio_entries (
            entry_id            TEXT PRIMARY KEY,
            date                TEXT,
            meal_type           TEXT,   -- breakfast / lunch / dinner / snack
            food_name           TEXT,
            brand               TEXT,
            amount_g            REAL,
            calories            REAL,
            protein_g           REAL,
            carbs_g             REAL,
            fat_g               REAL,
            fiber_g             REAL,
            sugar_g             REAL,
            raw_json            TEXT,
            fetched_at          TEXT
        );

        CREATE TABLE IF NOT EXISTS yazio_weight (
            date                TEXT PRIMARY KEY,
            weight_kg           REAL,
            raw_json            TEXT,
            fetched_at          TEXT
        );

        CREATE TABLE IF NOT EXISTS yazio_goals (
            fetched_at          TEXT PRIMARY KEY,
            calories_goal       INTEGER,
            protein_goal_g      REAL,
            carbs_goal_g        REAL,
            fat_goal_g          REAL,
            water_goal_ml       INTEGER,
            raw_json            TEXT
        );
    """)
    conn.commit()
    log.info(f"YAZIO tables ready in: {DB_PATH}")


# ── Auth ───────────────────────────────────────────────────────────────────────
class YazioAuth:
    """Handles OAuth2 token management with file-based caching."""

    def __init__(self):
        self.token: Optional[str] = None
        self.expires_at: float = 0.0
        self._load_cached_token()

    def _load_cached_token(self):
        if TOKEN_CACHE_FILE.exists():
            try:
                data = json.loads(TOKEN_CACHE_FILE.read_text())
                if data.get("expires_at", 0) > time.time() + 60:
                    self.token = data["access_token"]
                    self.expires_at = data["expires_at"]
                    log.info("✅ Cached YAZIO token geladen")
            except Exception:
                pass

    def _save_token(self, access_token: str, expires_in: int):
        self.token = access_token
        self.expires_at = time.time() + expires_in
        TOKEN_CACHE_FILE.write_text(json.dumps({
            "access_token": access_token,
            "expires_at": self.expires_at,
        }))

    def get_token(self) -> str:
        if self.token and time.time() < self.expires_at - 60:
            return self.token
        return self._login()

    def _login(self) -> str:
        if not YAZIO_EMAIL or not YAZIO_PASSWORD:
            raise SystemExit(
                "❌ YAZIO-Zugangsdaten fehlen. "
                "Setze YAZIO_EMAIL und YAZIO_PASSWORD in .env"
            )

        log.info(f"🔑 YAZIO Login für {YAZIO_EMAIL} ...")
        resp = requests.post(AUTH_URL, data={
            "grant_type": "password",
            "username": YAZIO_EMAIL,
            "password": YAZIO_PASSWORD,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }, timeout=15)

        if resp.status_code != 200:
            raise SystemExit(
                f"❌ YAZIO Login fehlgeschlagen ({resp.status_code}): {resp.text}"
            )

        data = resp.json()
        self._save_token(data["access_token"], data.get("expires_in", 3600))
        log.info("✅ YAZIO Login erfolgreich")
        return self.token

    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


# ── API Helpers ────────────────────────────────────────────────────────────────
def api_get(auth: YazioAuth, url: str, params: dict = None) -> Optional[dict]:
    """Safe GET wrapper with error handling."""
    try:
        resp = requests.get(url, headers=auth.headers(), params=params, timeout=15)
        if resp.status_code == 401:
            # Token expired — force re-login
            auth.token = None
            resp = requests.get(url, headers=auth.headers(), params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        log.warning(f"  ⚠️  {url} → HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        log.warning(f"  ⚠️  Request error {url}: {e}")
        return None


PRODUCT_URL = f"{API_BASE}/v20/products"
RECIPE_URL  = f"{API_BASE}/v20/recipes"

# Cache für Produktdaten (vermeidet doppelte Requests)
_product_cache: dict = {}


def fetch_nutrients(auth: YazioAuth, product_id: str) -> dict:
    """Fetch nutritional values for a product (per 100g)."""
    if product_id in _product_cache:
        return _product_cache[product_id]
    data = api_get(auth, f"{PRODUCT_URL}/{product_id}") or {}
    nutrients = data.get("nutritional_values", data.get("nutrients", {})) or {}
    _product_cache[product_id] = {"data": data, "nutrients": nutrients}
    return _product_cache[product_id]


def fetch_recipe_nutrients(auth: YazioAuth, recipe_id: str) -> dict:
    """Fetch nutritional values for a recipe (per portion)."""
    if recipe_id in _product_cache:
        return _product_cache[recipe_id]
    data = api_get(auth, f"{RECIPE_URL}/{recipe_id}") or {}
    _product_cache[recipe_id] = {"data": data, "nutrients": data}
    return _product_cache[recipe_id]


def calc_nutrients(nutrients_per_g: dict, amount_g: float) -> dict:
    """
    Scale YAZIO nutrients to actual eaten amount.
    YAZIO stores values per 1g in kg (protein, fat, carbs) or kJ (energy).
    We multiply by amount_g to get absolute values, then convert units.
    """
    # energy: kcal/g -> kcal total
    kcal = float(nutrients_per_g.get("energy.energy", 0) or 0) * amount_g
    # macros: g/g -> g total  (multiply by amount_g)
    factor_g = amount_g
    return {
        "calories": kcal,
        "protein":  float(nutrients_per_g.get("nutrient.protein",      0) or 0) * factor_g,
        "carbs":    float(nutrients_per_g.get("nutrient.carb",         0) or 0) * factor_g,
        "fat":      float(nutrients_per_g.get("nutrient.fat",          0) or 0) * factor_g,
        "fiber":    float(nutrients_per_g.get("nutrient.dietaryfiber", 0) or 0) * factor_g,
        "sugar":    float(nutrients_per_g.get("nutrient.sugar",        0) or 0) * factor_g,
    }


# ── Fetch & Store Functions ────────────────────────────────────────────────────
def fetch_diary_day(auth: YazioAuth, conn: sqlite3.Connection, day: date):
    """
    Fetch consumed items for one day.
    Step 1: GET /v20/user/consumed-items?date=...
    Step 2: For each product_id → GET /v20/products/{id}
            For each recipe_id  → GET /v20/recipes/{id}
    """
    d = day.isoformat()
    data = api_get(auth, DIARY_URL, {"date": d})
    if data is None:
        return None, None

    products        = data.get("products", []) or []
    recipe_portions = data.get("recipe_portions", []) or []

    meal_kcal = {"breakfast": 0.0, "lunch": 0.0, "dinner": 0.0, "snack": 0.0}
    total     = {"calories": 0.0, "protein": 0.0, "carbs": 0.0,
                 "fat": 0.0, "fiber": 0.0, "sugar": 0.0}
    stored = 0

    # ── Produkte ──────────────────────────────────────────────────────────────
    for item in products:
        entry_id   = item.get("id", "")
        product_id = item.get("product_id", "")
        amount_g   = float(item.get("amount", 0) or 0)
        meal_key   = item.get("daytime", "snack")
        if meal_key not in meal_kcal:
            meal_key = "snack"

        # Nährwerte per 100g laden
        product_info = fetch_nutrients(auth, product_id)
        n100 = product_info.get("nutrients", {})
        pdata = product_info.get("data", {})
        n = calc_nutrients(n100, amount_g)

        for k in total:
            total[k] += n[k]
        meal_kcal[meal_key] += n["calories"]

        if entry_id:
            conn.execute("""
                INSERT OR REPLACE INTO yazio_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                entry_id, d, meal_key,
                pdata.get("name", pdata.get("title")),
                pdata.get("brand", pdata.get("manufacturer")),
                amount_g,
                round(n["calories"], 2),
                round(n["protein"], 2),
                round(n["carbs"], 2),
                round(n["fat"], 2),
                round(n["fiber"], 2),
                round(n["sugar"], 2),
                json.dumps({"item": item, "product": pdata}),
                datetime.now().isoformat(),
            ))
            stored += 1
        time.sleep(0.1)  # API nicht überlasten

    # ── Rezepte ───────────────────────────────────────────────────────────────
    for portion in recipe_portions:
        entry_id       = portion.get("id", "")
        recipe_id      = portion.get("recipe_id", "")
        eaten_portions = float(portion.get("portion_count", 1) or 1)
        meal_key       = portion.get("daytime", "dinner")
        if meal_key not in meal_kcal:
            meal_key = "dinner"

        recipe_info    = fetch_recipe_nutrients(auth, recipe_id)
        rdata          = recipe_info.get("data", {})
        # Nährwerte sind bereits pro 1 Portion angegeben
        # eaten_portions = wie viele Portionen gegessen
        n_total = rdata.get("nutrients", {}) or {}
        factor  = eaten_portions
        n = {
            "calories": float(n_total.get("energy.energy", 0) or 0) * factor,
            "protein":  float(n_total.get("nutrient.protein",      0) or 0) * factor,
            "carbs":    float(n_total.get("nutrient.carb",         0) or 0) * factor,
            "fat":      float(n_total.get("nutrient.fat",          0) or 0) * factor,
            "fiber":    float(n_total.get("nutrient.dietaryfiber", 0) or 0) * factor,
            "sugar":    float(n_total.get("nutrient.sugar",        0) or 0) * factor,
        }

        for k in total:
            total[k] += n[k]
        meal_kcal[meal_key] += n["calories"]

        if entry_id:
            conn.execute("""
                INSERT OR REPLACE INTO yazio_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                entry_id, d, meal_key,
                rdata.get("name", rdata.get("title", "Rezept")),
                None,
                eaten_portions,
                round(n["calories"], 2),
                round(n["protein"], 2),
                round(n["carbs"], 2),
                round(n["fat"], 2),
                round(n["fiber"], 2),
                round(n["sugar"], 2),
                json.dumps({"portion": portion, "recipe": rdata}),
                datetime.now().isoformat(),
            ))
            stored += 1
        time.sleep(0.1)

    conn.commit()
    log.info(
        f"  ✅ Ernährung {d} | "
        f"{round(total['calories'])} kcal | "
        f"P: {round(total['protein'])}g "
        f"C: {round(total['carbs'])}g "
        f"F: {round(total['fat'])}g | "
        f"{stored} Einträge ({len(products)} Produkte, {len(recipe_portions)} Rezepte)"
    )
    return total, meal_kcal


def fetch_daily_summary(auth: YazioAuth, conn: sqlite3.Connection, day: date,
                        nutritional_totals: Optional[dict] = None,
                        meal_kcal: Optional[dict] = None):
    """Fetch or compute daily summary and store it."""
    d = day.isoformat()

    # Try the dedicated summary endpoint first
    summary_data = api_get(auth, SUMMARY_URL, {"date": d})

    # Fetch water separately
    water_data = api_get(auth, WATER_URL, {"date": d})
    water_ml = None
    if water_data:
        items = water_data.get("items", water_data) if isinstance(water_data, dict) else water_data
        if isinstance(items, list):
            water_ml = int(sum(
                float(w.get("amount", w.get("quantity", 0)) or 0) * 1000
                if str(w.get("unit", "l")).lower() in ("l", "liter") else
                float(w.get("amount", w.get("quantity", 0)) or 0)
                for w in items
            ))

    # Parse summary or fall back to computed totals
    s = {}
    if summary_data:
        s = summary_data.get("summary", summary_data) if isinstance(summary_data, dict) else {}

    calories_eaten  = s.get("calories", s.get("energy")) or (
        round(nutritional_totals["calories"]) if nutritional_totals else None)
    protein_g  = s.get("protein") or (round(nutritional_totals["protein"], 1) if nutritional_totals else None)
    carbs_g    = s.get("carbohydrates", s.get("carbs")) or (round(nutritional_totals["carbs"], 1) if nutritional_totals else None)
    fat_g      = s.get("fat") or (round(nutritional_totals["fat"], 1) if nutritional_totals else None)
    fiber_g    = s.get("fiber") or (round(nutritional_totals["fiber"], 1) if nutritional_totals else None)
    sugar_g    = s.get("sugar") or (round(nutritional_totals["sugar"], 1) if nutritional_totals else None)

    # Goals from summary
    calories_goal = s.get("caloriesGoal", s.get("calories_goal"))

    conn.execute("""
        INSERT OR REPLACE INTO yazio_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        d,
        calories_goal,
        calories_eaten,
        s.get("burnedCalories", s.get("calories_burned")),
        (int(calories_eaten or 0) - int(s.get("burnedCalories", 0) or 0)) or None,
        protein_g, carbs_g, fat_g, fiber_g, sugar_g,
        s.get("sodium"),
        water_ml,
        meal_kcal.get("breakfast") if meal_kcal else None,
        meal_kcal.get("lunch") if meal_kcal else None,
        meal_kcal.get("dinner") if meal_kcal else None,
        meal_kcal.get("snack") if meal_kcal else None,
        json.dumps({"summary": s, "water": water_data}),
        datetime.now().isoformat(),
    ))
    conn.commit()


def fetch_weight(auth: YazioAuth, conn: sqlite3.Connection,
                 start: date, end: date):
    """Fetch body weight measurements."""
    data = api_get(auth, WEIGHT_URL, {
        "from": start.isoformat(),
        "to": end.isoformat(),
    })
    if not data:
        return

    items = data.get("items", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return

    count = 0
    for item in items:
        item_date = (item.get("date") or item.get("created_at", ""))[:10]
        if not item_date:
            continue
        weight = item.get("value", item.get("weight"))
        if weight is None:
            continue
        conn.execute("""
            INSERT OR REPLACE INTO yazio_weight VALUES (?,?,?,?)
        """, (item_date, float(weight), json.dumps(item), datetime.now().isoformat()))
        count += 1

    conn.commit()
    log.info(f"  ✅ Gewicht: {start} → {end} | {count} Einträge")


def fetch_goals(auth: YazioAuth, conn: sqlite3.Connection):
    """Fetch user nutrition goals."""
    data = api_get(auth, GOALS_URL)
    if not data:
        return

    g = data.get("goals", data) if isinstance(data, dict) else {}
    conn.execute("""
        INSERT OR REPLACE INTO yazio_goals VALUES (?,?,?,?,?,?,?)
    """, (
        datetime.now().isoformat(),
        g.get("calories", g.get("energy")),
        g.get("protein"),
        g.get("carbohydrates", g.get("carbs")),
        g.get("fat"),
        g.get("water") and int(float(g["water"]) * 1000),
        json.dumps(g),
    ))
    conn.commit()
    log.info(f"  ✅ Ziele gespeichert | Kalorien-Ziel: {g.get('calories', '?')} kcal")


# ── Export ─────────────────────────────────────────────────────────────────────
def export_json(conn: sqlite3.Connection,
                output_path: str = "yazio_export.json"):
    """Export all YAZIO data as JSON."""
    tables = ["yazio_daily", "yazio_entries", "yazio_weight", "yazio_goals"]
    export = {}
    for table in tables:
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY rowid DESC"
        ).fetchall()
        cols = [d[0] for d in conn.execute(
            f"SELECT * FROM {table} LIMIT 0"
        ).description]
        export[table] = [dict(zip(cols, row)) for row in rows]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)
    log.info(f"✅ Export: {output_path}")


def print_summary(conn: sqlite3.Connection, days: int = 7):
    """Print a quick overview of recent nutrition data."""
    print("\n" + "═" * 70)
    print(f"  🥗 YAZIO Daten – Letzte {days} Tage")
    print("═" * 70)

    rows = conn.execute(f"""
        SELECT date, calories_eaten, calories_goal,
               protein_g, carbs_g, fat_g, water_ml
        FROM yazio_daily
        ORDER BY date DESC LIMIT {days}
    """).fetchall()

    print(f"  {'Datum':<12} {'Kcal':>6} {'Ziel':>5} {'P(g)':>6} "
          f"{'C(g)':>6} {'F(g)':>6} {'Wasser':>7}")
    print("  " + "-" * 56)
    for r in rows:
        water = f"{r[6]}ml" if r[6] else "–"
        goal_pct = f"{round(r[1]/r[2]*100)}%" if r[1] and r[2] else "–"
        print(f"  {r[0]:<12} {str(r[1] or '–'):>6} {goal_pct:>5} "
              f"{str(round(r[3] or 0)):>6} {str(round(r[4] or 0)):>6} "
              f"{str(round(r[5] or 0)):>6} {water:>7}")

    weight_rows = conn.execute("""
        SELECT date, weight_kg FROM yazio_weight
        ORDER BY date DESC LIMIT 5
    """).fetchall()
    if weight_rows:
        print(f"\n  ⚖️  Gewicht (letzte Einträge):")
        for r in weight_rows:
            print(f"     {r[0]}: {r[1]:.1f} kg")

    entry_count = conn.execute(
        "SELECT COUNT(*) FROM yazio_entries"
    ).fetchone()[0]
    print(f"\n  🍽️  Lebensmittel-Einträge gesamt: {entry_count}")
    print("═" * 70 + "\n")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="YAZIO Data Connector")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--today",   action="store_true", help="Nur heute")
    group.add_argument("--days",    type=int, metavar="N", help="Letzte N Tage")
    group.add_argument("--from",    dest="start", metavar="YYYY-MM-DD")
    parser.add_argument("--to",     dest="end",   metavar="YYYY-MM-DD",
                        default=date.today().isoformat())
    parser.add_argument("--export", choices=["json"], help="JSON-Export")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    # Date range
    if args.today:
        start_date = end_date = date.today()
    elif args.days:
        end_date   = date.today()
        start_date = end_date - timedelta(days=args.days - 1)
    elif args.start:
        start_date = date.fromisoformat(args.start)
        end_date   = date.fromisoformat(args.end)
    else:
        start_date = end_date = date.today()

    # DB
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    if args.export == "json":
        export_json(conn)
        return

    if args.summary:
        print_summary(conn)
        return

    # Auth
    auth = YazioAuth()

    # Fetch goals once
    log.info("\n🎯 Lade Ernährungsziele ...")
    fetch_goals(auth, conn)

    # Fetch weight for range
    log.info(f"\n⚖️  Lade Gewichtsdaten ({start_date} → {end_date}) ...")
    fetch_weight(auth, conn, start_date, end_date)

    # Day-by-day diary
    current = start_date
    while current <= end_date:
        log.info(f"\n📅 Verarbeite: {current.isoformat()}")
        result = fetch_diary_day(auth, conn, current)
        totals, meals = result if result else (None, None)
        fetch_daily_summary(auth, conn, current, totals, meals)
        current += timedelta(days=1)
        time.sleep(0.3)   # be polite to the API

    print_summary(conn, days=min(7, (end_date - start_date).days + 1))
    log.info("✅ YAZIO Sync abgeschlossen!")
    conn.close()


if __name__ == "__main__":
    main()
