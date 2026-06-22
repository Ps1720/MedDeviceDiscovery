"""
SQLite-backed perioperative protocol knowledge base.

Stores device-class resolution rules and class/context-scoped clinical guidance
(magnet behavior, electrocautery precautions, checklists, manufacturer support
lines) seeded at startup by protocol_seed.py. The runtime source of truth is
this database; institution-specific overrides live separately in
data/institution_overrides.json (see overrides.py).

Every content row carries requires_verification (default 1): seeded clinical
text is a structural placeholder until a clinician confirms it against the
cited guideline or manufacturer labeling.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("PROTOCOL_DB_PATH", "data/protocols.db"))

CONTEXTS = ("surgery", "mri", "ep_study")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS ifu_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    di              TEXT,
    manufacturer    TEXT,
    brand           TEXT,
    model           TEXT,
    ifu_url         TEXT,
    ifu_hash        TEXT,
    last_fetched    TEXT,
    finder_source   TEXT,
    extraction_raw  TEXT,
    extracted_by    TEXT DEFAULT 'llm',
    extracted_at    TEXT,
    verified_by     TEXT,
    verified_at     TEXT,
    conflict_flags  TEXT,
    status          TEXT DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_ifu_di ON ifu_records (di);

CREATE TABLE IF NOT EXISTS device_classes (
    class_key    TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    module       TEXT NOT NULL,
    description  TEXT
);

CREATE TABLE IF NOT EXISTS class_resolution_rules (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    class_key TEXT NOT NULL REFERENCES device_classes(class_key),
    rule_type TEXT NOT NULL,
    value     TEXT NOT NULL,
    priority  INTEGER NOT NULL DEFAULT 100,
    notes     TEXT
);
CREATE INDEX IF NOT EXISTS idx_rules_type ON class_resolution_rules (rule_type, value);

CREATE TABLE IF NOT EXISTS brand_model_rules (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_pattern TEXT,
    brand_pattern        TEXT,
    resolves_class       TEXT NOT NULL REFERENCES device_classes(class_key),
    priority             INTEGER NOT NULL DEFAULT 50,
    notes                TEXT
);

CREATE TABLE IF NOT EXISTS protocol_facts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    class_key             TEXT NOT NULL REFERENCES device_classes(class_key),
    context               TEXT NOT NULL DEFAULT 'all',
    fact_key              TEXT NOT NULL,
    fact_value            TEXT NOT NULL,
    detail                TEXT,
    severity              TEXT,
    guideline_source      TEXT,
    guideline_year        TEXT,
    citation              TEXT,
    requires_verification INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_facts ON protocol_facts (class_key, context);

CREATE TABLE IF NOT EXISTS checklist_items (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    class_key             TEXT NOT NULL REFERENCES device_classes(class_key),
    context               TEXT NOT NULL DEFAULT 'surgery',
    position              INTEGER NOT NULL,
    item_text             TEXT NOT NULL,
    rationale             TEXT,
    guideline_source      TEXT,
    citation              TEXT,
    requires_verification INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_checklist ON checklist_items (class_key, context, position);

CREATE TABLE IF NOT EXISTS brand_facts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer_pattern  TEXT,
    brand_pattern         TEXT,
    class_key             TEXT,
    fact_key              TEXT NOT NULL,
    fact_value            TEXT NOT NULL,
    detail                TEXT,
    citation              TEXT,
    requires_verification INTEGER NOT NULL DEFAULT 1,
    source                TEXT DEFAULT 'seeded',
    source_url            TEXT,
    extracted_at          TEXT,
    ifu_record_id         INTEGER REFERENCES ifu_records(id)
);
"""

CONTENT_TABLES = (
    "device_classes",
    "class_resolution_rules",
    "brand_model_rules",
    "protocol_facts",
    "checklist_items",
    "brand_facts",
)


def get_conn(path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Add columns introduced after initial schema — idempotent."""
    new_cols = [
        ("brand_facts", "source", "TEXT DEFAULT 'seeded'"),
        ("brand_facts", "source_url", "TEXT"),
        ("brand_facts", "extracted_at", "TEXT"),
        ("brand_facts", "ifu_record_id", "INTEGER"),
    ]
    for table, col, typedef in new_cols:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()


def init_db(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    conn = conn or get_conn()
    try:
        conn.executescript(_SCHEMA)
        _run_migrations(conn)
        conn.commit()
    finally:
        if own:
            conn.close()


def get_meta(key: str, conn: Optional[sqlite3.Connection] = None) -> Optional[str]:
    own = conn is None
    conn = conn or get_conn()
    try:
        row = conn.execute("SELECT value FROM kb_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        if own:
            conn.close()


def get_device_classes(conn: Optional[sqlite3.Connection] = None) -> dict[str, dict]:
    """All device classes keyed by class_key."""
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute("SELECT * FROM device_classes").fetchall()
        return {r["class_key"]: dict(r) for r in rows}
    finally:
        if own:
            conn.close()


def get_resolution_rules(conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM class_resolution_rules ORDER BY priority, id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_brand_model_rules(conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM brand_model_rules ORDER BY priority, id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_facts(
    class_key: str, context: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, dict]:
    """
    Facts for a class in a context, keyed by fact_key. Context-specific rows
    shadow 'all' rows with the same fact_key.
    """
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM protocol_facts
            WHERE class_key = ? AND context IN (?, 'all')
            ORDER BY CASE context WHEN 'all' THEN 0 ELSE 1 END, id
            """,
            (class_key, context),
        ).fetchall()
        facts: dict[str, dict] = {}
        for r in rows:  # later (context-specific) rows overwrite 'all' rows
            facts[r["fact_key"]] = dict(r)
        return facts
    finally:
        if own:
            conn.close()


def get_checklist(
    class_key: str, context: str, conn: Optional[sqlite3.Connection] = None
) -> list[dict]:
    """
    Checklist for a class in a context. If any rows exist for the specific
    context, only those are used; otherwise fall back to 'all'.
    """
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM checklist_items WHERE class_key = ? AND context = ? "
            "ORDER BY position, id",
            (class_key, context),
        ).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT * FROM checklist_items WHERE class_key = ? AND context = 'all' "
                "ORDER BY position, id",
                (class_key,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_available_contexts(
    class_key: str, conn: Optional[sqlite3.Connection] = None
) -> list[str]:
    """Contexts for which this class has any specific facts or checklist items."""
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT context FROM protocol_facts WHERE class_key = ?
            UNION
            SELECT DISTINCT context FROM checklist_items WHERE class_key = ?
            """,
            (class_key, class_key),
        ).fetchall()
        found = {r["context"] for r in rows}
        if "all" in found:
            return list(CONTEXTS)
        return [c for c in CONTEXTS if c in found]
    finally:
        if own:
            conn.close()


def upsert_ifu_record(fields: dict, conn: Optional[sqlite3.Connection] = None) -> int:
    """
    Insert or update an IFU record. Matches on (di, ifu_url) when di is set,
    otherwise on (manufacturer, brand, model, ifu_url). Returns the row id.
    """
    own = conn is None
    conn = conn or get_conn()
    try:
        di = fields.get("di")
        ifu_url = fields.get("ifu_url")
        if di and ifu_url:
            existing = conn.execute(
                "SELECT id FROM ifu_records WHERE di = ? AND ifu_url = ?", (di, ifu_url)
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM ifu_records WHERE manufacturer = ? AND brand = ? AND model = ? AND ifu_url = ?",
                (fields.get("manufacturer"), fields.get("brand"), fields.get("model"), ifu_url),
            ).fetchone()
        cols = list(fields.keys())
        vals = [fields[c] for c in cols]
        if existing:
            set_clause = ", ".join(f"{c} = ?" for c in cols)
            conn.execute(
                f"UPDATE ifu_records SET {set_clause} WHERE id = ?", vals + [existing["id"]]
            )
            conn.commit()
            return existing["id"]
        placeholders = ", ".join("?" * len(cols))
        cur = conn.execute(
            f"INSERT INTO ifu_records ({', '.join(cols)}) VALUES ({placeholders})", vals
        )
        conn.commit()
        return cur.lastrowid
    finally:
        if own:
            conn.close()


def get_ifu_record(record_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    own = conn is None
    conn = conn or get_conn()
    try:
        row = conn.execute("SELECT * FROM ifu_records WHERE id = ?", (record_id,)).fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()


def list_ifu_records(conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """All IFU records ordered by most recently fetched."""
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ifu_records ORDER BY last_fetched DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_brand_facts(
    manufacturer: str,
    brand_blob: str,
    class_key: Optional[str],
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, dict]:
    """
    Brand/manufacturer-specific facts matching this device, keyed by fact_key.
    Patterns are case-insensitive substrings; NULL patterns match anything.
    More specific rows (both patterns set) win over manufacturer-only rows.
    """
    manufacturer = (manufacturer or "").lower()
    brand_blob = (brand_blob or "").lower()
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM brand_facts WHERE class_key IS NULL OR class_key = ? ORDER BY id",
            (class_key,),
        ).fetchall()
        matched: list[tuple[int, dict]] = []
        for r in rows:
            mfr_pat = (r["manufacturer_pattern"] or "").lower()
            brand_pat = (r["brand_pattern"] or "").lower()
            if mfr_pat and mfr_pat not in manufacturer:
                continue
            if brand_pat and brand_pat not in brand_blob:
                continue
            specificity = (1 if mfr_pat else 0) + (2 if brand_pat else 0)
            matched.append((specificity, dict(r)))
        matched.sort(key=lambda t: t[0])  # least specific first; most specific wins
        facts: dict[str, dict] = {}
        for _, row in matched:
            facts[row["fact_key"]] = row
        return facts
    finally:
        if own:
            conn.close()
