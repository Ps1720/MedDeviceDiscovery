"""
SQLite-backed device-recall cache for the CDS Hooks recall-check service.

Recalls are keyed by UDI Device Identifier (DI) so they can be matched against a
patient's FHIR Device.udiCarrier.deviceIdentifier. (openFDA's device/recall feed
is NOT UDI-DI indexed — see recall_poller.py — so DI-level matching relies on
curated/demo entries; the openFDA pull is stored for reference/coverage.)
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("RECALLS_DB_PATH", "data/recalls.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recalls (
    device_identifier      TEXT NOT NULL,
    recall_number          TEXT NOT NULL,
    classification         TEXT,
    reason                 TEXT,
    recall_initiation_date TEXT,
    status                 TEXT,
    firm                   TEXT,
    source                 TEXT,
    PRIMARY KEY (device_identifier, recall_number)
);
CREATE INDEX IF NOT EXISTS idx_recalls_di ON recalls (device_identifier);
"""


def get_conn(path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    conn = conn or get_conn()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        if own:
            conn.close()


def upsert_recall(row: dict, conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    conn = conn or get_conn()
    try:
        conn.execute(
            """
            INSERT INTO recalls (device_identifier, recall_number, classification,
                                 reason, recall_initiation_date, status, firm, source)
            VALUES (:device_identifier, :recall_number, :classification, :reason,
                    :recall_initiation_date, :status, :firm, :source)
            ON CONFLICT(device_identifier, recall_number) DO UPDATE SET
                classification=excluded.classification,
                reason=excluded.reason,
                recall_initiation_date=excluded.recall_initiation_date,
                status=excluded.status,
                firm=excluded.firm,
                source=excluded.source
            """,
            {
                "device_identifier": row.get("device_identifier") or "",
                "recall_number": row.get("recall_number") or "",
                "classification": row.get("classification"),
                "reason": row.get("reason"),
                "recall_initiation_date": row.get("recall_initiation_date"),
                "status": row.get("status"),
                "firm": row.get("firm"),
                "source": row.get("source", "openfda"),
            },
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def recalls_for_di(di: str, conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    if not di:
        return []
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM recalls WHERE device_identifier = ? ORDER BY recall_initiation_date DESC",
            (di,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def count(conn: Optional[sqlite3.Connection] = None) -> int:
    own = conn is None
    conn = conn or get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM recalls").fetchone()[0]
    finally:
        if own:
            conn.close()
