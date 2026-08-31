import sqlite3
from datetime import date

conn = sqlite3.connect("data/eventi.db")
print("fonti totali:", conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
print("fonti processate:", conn.execute("SELECT COUNT(DISTINCT source_id) FROM artifacts").fetchone()[0])
print("eventi trovati:", conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
oggi = date.today().isoformat()
chiamate = conn.execute("SELECT COUNT(*) FROM extractions WHERE created_at LIKE ?", (oggi + "%",)).fetchone()[0]
print("chiamate LLM oggi:", chiamate, "/ 1200")
