from pathlib import Path
import sqlite3
import json
from typing import Any, Dict

DB_PATH = Path("game.sqlite")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def exec1(conn, sql: str, args=()):
    cur = conn.cursor()
    cur.execute(sql, args)
    conn.commit()
    return cur

def q(conn, sql: str, args=()):
    cur = conn.cursor()
    cur.execute(sql, args)
    return cur.fetchall()

def _table_exists(conn, name: str) -> bool:
    rows = q(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return bool(rows)

def _column_exists(conn, table: str, col: str) -> bool:
    rows = q(conn, f"PRAGMA table_info({table})")
    return any(r["name"] == col for r in rows)

def init_db():
    conn = get_conn()
    # users
    exec1(conn, """
    CREATE TABLE IF NOT EXISTS users(
      id TEXT PRIMARY KEY,
      name TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    # plants (add name column for labeling)
    exec1(conn, """
    CREATE TABLE IF NOT EXISTS plants(
      id TEXT PRIMARY KEY,
      user_id TEXT,
      species TEXT,
      genome_json TEXT,
      age_days INTEGER,
      health REAL,
      generation TEXT,
      stage TEXT,
      can_breed INTEGER DEFAULT 1,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    # safe migration: add name if missing
    if not _column_exists(conn, "plants", "name"):
        exec1(conn, "ALTER TABLE plants ADD COLUMN name TEXT")

    # seeds (each lot is a genotype + qty)
    exec1(conn, """
    CREATE TABLE IF NOT EXISTS seeds(
      id TEXT PRIMARY KEY,
      user_id TEXT,
      species TEXT,
      genome_json TEXT,
      qty INTEGER,
      generation TEXT,
      parents_json TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    # fruits (in-progress pods before harvest)
    exec1(conn, """
    CREATE TABLE IF NOT EXISTS fruits(
      id TEXT PRIMARY KEY,
      user_id TEXT,
      species TEXT,
      mom_id TEXT,
      dad_id TEXT,
      genome_json TEXT,
      qty INTEGER,
      generation TEXT,
      days_remaining INTEGER,
      status TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    # slots (greenhouse)
    exec1(conn, """
    CREATE TABLE IF NOT EXISTS slots(
      id TEXT PRIMARY KEY,
      user_id TEXT,
      plant_id TEXT,
      soil TEXT,
      light TEXT,
      water TEXT,
      temp TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.close()
