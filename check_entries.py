import sqlite3
conn = sqlite3.connect('garmin_data.db')
rows = conn.execute("""
    SELECT meal_type, food_name, amount_g, calories, protein_g, carbs_g, fat_g
    FROM yazio_entries WHERE date='2026-03-11' ORDER BY meal_type
""").fetchall()
for r in rows:
    name = str(r[1] or "")[:30]
    print(f"{r[0]:10} {name:30} {r[2]:6.0f}g  {r[3]:6.1f} kcal  P:{r[4]:.1f} C:{r[5]:.1f} F:{r[6]:.1f}")

print()
total = conn.execute("""
    SELECT SUM(calories), SUM(protein_g), SUM(carbs_g), SUM(fat_g)
    FROM yazio_entries WHERE date='2026-03-09'
""").fetchone()
print(f"TOTAL: {total[0]:.0f} kcal  P:{total[1]:.0f}g  C:{total[2]:.0f}g  F:{total[3]:.0f}g")
