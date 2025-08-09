import sqlite3
from pathlib import Path
from typing import List

DB_PATH = Path("game.sqlite")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS seeds (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  species TEXT NOT NULL,
  genome_json TEXT NOT NULL,
  qty INTEGER NOT NULL,
  generation TEXT DEFAULT 'F1',
  parents_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS plants (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  species TEXT NOT NULL,
  genome_json TEXT NOT NULL,
  age_days INTEGER NOT NULL DEFAULT 0,
  health REAL NOT NULL DEFAULT 1.0,
  generation TEXT DEFAULT 'F1',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id)
);
"""

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA)
        # Migrations if Day-1 DB existed
        try:
            conn.execute("ALTER TABLE plants ADD COLUMN generation TEXT DEFAULT 'F1'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE seeds ADD COLUMN parents_json TEXT")
        except sqlite3.OperationalError:
            pass
    conn.close()

def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    cur = conn.execute(sql, params)
    return cur.fetchall()

def exec1(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    conn.execute(sql, params)
    conn.commit()