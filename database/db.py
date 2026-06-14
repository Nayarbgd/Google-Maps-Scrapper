"""
SQLite session manager for the Google Maps Scraper.

Tables:
    sessions — one row per scrape run
    places   — one row per business, linked to a session
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
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL,
            name            TEXT,
            address         TEXT,
            website         TEXT,
            phone_number    TEXT,
            email           TEXT,
            reviews_count   INTEGER,
            reviews_average REAL,
            place_type      TEXT,
            opens_at        TEXT,
            open_status     TEXT,
            store_shopping  TEXT,
            in_store_pickup TEXT,
            store_delivery  TEXT,
            introduction    TEXT,
            scraped_at      TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
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
           store_shopping, in_store_pickup, store_delivery, introduction, scraped_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
