"""
SQLite session manager for the Google Maps Scraper.

Tables:
    sessions — one row per scrape run
    places   — one row per business, linked to a session
    pipeline — personal CRM leads selected from scrape results
"""
import sqlite3
import json
import os
from datetime import datetime
from dataclasses import asdict
from typing import List, Dict, Any, Optional

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            query       TEXT    NOT NULL,
            total_req   INTEGER DEFAULT 0,
            total_found INTEGER DEFAULT 0,
            dup_skipped INTEGER DEFAULT 0,
            filtered    INTEGER DEFAULT 0,
            filters     TEXT,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS places (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id           INTEGER NOT NULL,
            name                 TEXT,
            address              TEXT,
            website              TEXT,
            phone_number         TEXT,
            email                TEXT,
            reviews_count        INTEGER,
            reviews_average      REAL,
            place_type           TEXT,
            opens_at             TEXT,
            open_status          TEXT,
            store_shopping       TEXT,
            in_store_pickup      TEXT,
            store_delivery       TEXT,
            introduction         TEXT,
            scraped_at           TEXT,
            website_status       TEXT,
            website_error_reason TEXT,
            website_confidence   INTEGER,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)
    for col, col_type in [("website_status", "TEXT"), ("website_error_reason", "TEXT"), ("website_confidence", "INTEGER")]:
        try:
            conn.execute(f"ALTER TABLE places ADD COLUMN {col} {col_type}")
        except Exception:
            pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pipeline (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT    NOT NULL,
            phone         TEXT    DEFAULT '',
            website       TEXT    DEFAULT '',
            email         TEXT    DEFAULT '',
            status        TEXT    DEFAULT '🟡 To Contact',
            notes         TEXT    DEFAULT '',
            date_added    TEXT    NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def create_session(query: str, total_req: int, filters: Optional[Dict] = None) -> int:
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO sessions (query, total_req, filters, created_at) VALUES (?,?,?,?)",
        (query, total_req, json.dumps(filters) if filters else None, datetime.now().isoformat()),
    )
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return sid


def save_place(session_id: int, place) -> None:
    d = asdict(place)
    conn = _connect()
    conn.execute(
        """
        INSERT INTO places
          (session_id, name, address, website, phone_number, email,
           reviews_count, reviews_average, place_type, opens_at, open_status,
           store_shopping, in_store_pickup, store_delivery, introduction, scraped_at,
           website_status, website_error_reason, website_confidence)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            session_id,
            d.get("name", ""),
            d.get("address", ""),
            d.get("website", ""),
            d.get("phone_number", ""),
            d.get("email", ""),
            d.get("reviews_count"),
            d.get("reviews_average"),
            d.get("place_type", ""),
            d.get("opens_at", ""),
            d.get("open_status", ""),
            d.get("store_shopping", "No"),
            d.get("in_store_pickup", "No"),
            d.get("store_delivery", "No"),
            d.get("introduction", ""),
            datetime.now().isoformat(),
            d.get("website_status", ""),
            d.get("website_error_reason", ""),
            d.get("website_confidence", -1),
        ),
    )
    conn.commit()
    conn.close()


def update_session(session_id: int, total_found: int, dup_skipped: int = 0, filtered: int = 0) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE sessions SET total_found=?, dup_skipped=?, filtered=?, updated_at=? WHERE id=?",
        (total_found, dup_skipped, filtered, datetime.now().isoformat(), session_id),
    )
    conn.commit()
    conn.close()


def list_sessions() -> List[Dict]:
    conn = _connect()
    rows = conn.execute(
        """
        SELECT id, query, total_req, total_found, dup_skipped, filtered, created_at
        FROM sessions ORDER BY created_at DESC LIMIT 100
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session_places(session_id: int) -> List[Dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM places WHERE session_id=? ORDER BY id", (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_session(session_id: int) -> None:
    conn = _connect()
    conn.execute("DELETE FROM places WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()


def places_to_dataframe(places: List[Dict]):
    import pandas as pd
    return pd.DataFrame(places)


# ── Pipeline CRUD ─────────────────────────────────────────────────────────────

def pipeline_add(business_name: str, phone: str = '', website: str = '', email: str = '') -> Optional[Dict]:
    conn = _connect()
    existing = conn.execute(
        "SELECT id FROM pipeline WHERE business_name=?", (business_name,)
    ).fetchone()
    if existing:
        conn.close()
        return None
    cur = conn.execute(
        "INSERT INTO pipeline (business_name, phone, website, email, status, notes, date_added) VALUES (?,?,?,?,?,?,?)",
        (business_name, phone or '', website or '', email or '', '🟡 To Contact', '', datetime.now().isoformat()),
    )
    row_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM pipeline WHERE id=?", (row_id,)).fetchone()
    conn.close()
    return dict(row)


def pipeline_list() -> List[Dict]:
    conn = _connect()
    rows = conn.execute("SELECT * FROM pipeline ORDER BY date_added DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def pipeline_update(row_id: int, status: Optional[str] = None, notes: Optional[str] = None) -> bool:
    conn = _connect()
    if status is not None and notes is not None:
        conn.execute("UPDATE pipeline SET status=?, notes=? WHERE id=?", (status, notes, row_id))
    elif status is not None:
        conn.execute("UPDATE pipeline SET status=? WHERE id=?", (status, row_id))
    elif notes is not None:
        conn.execute("UPDATE pipeline SET notes=? WHERE id=?", (notes, row_id))
    conn.commit()
    affected = conn.execute("SELECT changes()").fetchone()[0]
    conn.close()
    return affected > 0


def pipeline_delete(row_id: int) -> bool:
    conn = _connect()
    conn.execute("DELETE FROM pipeline WHERE id=?", (row_id,))
    conn.commit()
    affected = conn.execute("SELECT changes()").fetchone()[0]
    conn.close()
    return affected > 0
