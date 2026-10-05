import sqlite3
from src.db import DB_PATH

print("DB path:", DB_PATH)

conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
conn.close()

print("Tables:", rows)