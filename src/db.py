import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict

DB_PATH = "workspace/runs.db"

def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            requirement TEXT NOT NULL,
            status TEXT DEFAULT 'queued',
            iteration INTEGER DEFAULT 0,
            is_ready INTEGER DEFAULT 0,
            code_file TEXT,
            test_results TEXT,
            events TEXT DEFAULT '[]',
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def create_run(run_id: str, requirement: str) -> Dict:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO runs (id, requirement, status) VALUES (?, ?, ?)",
        (run_id, requirement, "queued")
    )
    conn.commit()
    conn.close()
    return {"id": run_id, "requirement": requirement, "status": "queued"}

def update_run(run_id: str, **kwargs):
    """Update run fields dynamically"""
    if not kwargs:
        return
    conn = sqlite3.connect(DB_PATH)
    fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
    values = list(kwargs.values()) + [run_id]
    conn.execute(
        f"UPDATE runs SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        values
    )
    conn.commit()
    conn.close()

def get_run(run_id: str) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    result["events"] = json.loads(result.get("events") or "[]")
    result["is_ready"] = bool(result["is_ready"])
    return result

def list_runs(limit: int = 20) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, requirement, status, iteration, is_ready, created_at "
        "FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def append_event(run_id: str, event: Dict):
    """Append an event to the run's event log"""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT events FROM runs WHERE id = ?", (run_id,)).fetchone()
    events = json.loads(row[0]) if row and row[0] else []
    events.append({**event, "timestamp": datetime.utcnow().isoformat()})
    conn.execute(
        "UPDATE runs SET events = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(events), run_id)
    )
    conn.commit()
    conn.close()