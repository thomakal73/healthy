import sqlite3
conn = sqlite3.connect('garmin_data.db')
rows = conn.execute("""
    SELECT date, name, activity_type,
           duration_sec/60 as min,
           distance_m/1000 as km,
           calories, avg_hr, steps
    FROM activities ORDER BY date DESC LIMIT 20
""").fetchall()

print(f"{'Datum':<12} {'Name':<28} {'Typ':<18} {'Min':>5} {'km':>6} {'Kcal':>5} {'HR':>4} {'Steps':>6}")
print("-" * 90)
for r in rows:
    name = str(r[1] or "")[:27]
    typ  = str(r[2] or "")[:17]
    km   = f"{r[4]:.1f}" if r[4] else "–"
    print(f"{r[0]:<12} {name:<28} {typ:<18} {r[3]:>5.0f} {km:>6} {str(r[5] or '–'):>5} {str(r[6] or '–'):>4} {str(r[7] or '–'):>6}")

print(f"\nGesamt: {len(rows)} Aktivitäten")
