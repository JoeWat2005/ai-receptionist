"""SQLite schema and persistence helpers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).resolve().parent / "clinic_receptionist.db"

LEAD_FIELDS = [
    "treatment_interest",
    "booking_type",
    "preferred_date",
    "preferred_time",
    "timeframe",
    "name",
    "phone",
    "email",
    "notes",
]


def get_connection() -> sqlite3.Connection:
    """Open SQLite connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _table_has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    """Check if a SQLite table includes a specific column."""
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Add newly introduced columns for existing local DB files."""
    if not _table_has_column(conn, "clinics", "slot_length_minutes"):
        conn.execute(
            "ALTER TABLE clinics ADD COLUMN slot_length_minutes INTEGER NOT NULL DEFAULT 30"
        )

    if not _table_has_column(conn, "clinics", "timezone"):
        conn.execute(
            "ALTER TABLE clinics ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Europe/London'"
        )

    if not _table_has_column(conn, "bookings", "duration_minutes"):
        conn.execute(
            "ALTER TABLE bookings ADD COLUMN duration_minutes INTEGER NOT NULL DEFAULT 30"
        )


def init_db() -> None:
    """Create required schema and apply lightweight migrations."""
    schema = """
    CREATE TABLE IF NOT EXISTS clinics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        location TEXT NOT NULL,
        timezone TEXT NOT NULL DEFAULT 'Europe/London',
        opening_hours_text TEXT NOT NULL,
        business_hours_json TEXT NOT NULL,
        slot_length_minutes INTEGER NOT NULL DEFAULT 30,
        treatments_json TEXT NOT NULL,
        faq_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clinic_id INTEGER NOT NULL,
        started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (clinic_id) REFERENCES clinics(id)
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
    );

    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL UNIQUE,
        clinic_id INTEGER NOT NULL,
        treatment_interest TEXT,
        booking_type TEXT,
        preferred_date TEXT,
        preferred_time TEXT,
        timeframe TEXT,
        name TEXT,
        phone TEXT,
        email TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
        FOREIGN KEY (clinic_id) REFERENCES clinics(id)
    );

    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL UNIQUE,
        clinic_id INTEGER NOT NULL,
        lead_id INTEGER,
        treatment_interest TEXT,
        booking_type TEXT,
        preferred_date TEXT,
        preferred_time TEXT,
        duration_minutes INTEGER NOT NULL DEFAULT 30,
        status TEXT NOT NULL,
        outcome_reason TEXT NOT NULL,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id),
        FOREIGN KEY (clinic_id) REFERENCES clinics(id),
        FOREIGN KEY (lead_id) REFERENCES leads(id)
    );

    CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
    CREATE INDEX IF NOT EXISTS idx_bookings_date_status ON bookings(clinic_id, preferred_date, status);
    CREATE INDEX IF NOT EXISTS idx_leads_clinic_id ON leads(clinic_id);
    """

    with get_connection() as conn:
        conn.executescript(schema)
        _run_migrations(conn)


def ensure_default_clinic(clinic_data: dict[str, Any]) -> int:
    """Insert default clinic once and return clinic id."""
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM clinics WHERE name = ? AND location = ? LIMIT 1",
            (clinic_data["name"], clinic_data["location"]),
        ).fetchone()
        if existing:
            return int(existing["id"])

        cursor = conn.execute(
            """
            INSERT INTO clinics (
                name,
                location,
                timezone,
                opening_hours_text,
                business_hours_json,
                slot_length_minutes,
                treatments_json,
                faq_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clinic_data["name"],
                clinic_data["location"],
                clinic_data.get("timezone", "Europe/London"),
                clinic_data["opening_hours_text"],
                json.dumps(clinic_data["business_hours"]),
                int(clinic_data.get("slot_length_minutes", 30)),
                json.dumps(clinic_data["treatments"]),
                json.dumps(clinic_data["faq"]),
            ),
        )
        return int(cursor.lastrowid)


def get_clinic(clinic_id: int) -> dict[str, Any]:
    """Return one clinic row with decoded JSON fields."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM clinics WHERE id = ? LIMIT 1", (clinic_id,)).fetchone()

    if not row:
        raise RuntimeError(f"Clinic not found for id={clinic_id}")

    clinic = dict(row)
    clinic["business_hours"] = json.loads(clinic["business_hours_json"])
    clinic["treatments"] = json.loads(clinic["treatments_json"])
    clinic["faq"] = json.loads(clinic["faq_json"])
    clinic["slot_length_minutes"] = int(clinic.get("slot_length_minutes") or 30)
    clinic["timezone"] = clinic.get("timezone") or "Europe/London"
    return clinic


def update_clinic_settings(
    clinic_id: int,
    business_hours: dict[str, Any],
    opening_hours_text: str,
    slot_length_minutes: int,
    timezone: Optional[str] = None,
) -> None:
    """Update editable clinic settings from dashboard."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE clinics
            SET business_hours_json = ?,
                opening_hours_text = ?,
                slot_length_minutes = ?,
                timezone = COALESCE(?, timezone)
            WHERE id = ?
            """,
            (
                json.dumps(business_hours),
                opening_hours_text,
                int(slot_length_minutes),
                timezone,
                clinic_id,
            ),
        )


def create_conversation(clinic_id: int) -> int:
    """Create a new conversation and return id."""
    with get_connection() as conn:
        cursor = conn.execute("INSERT INTO conversations (clinic_id) VALUES (?)", (clinic_id,))
        return int(cursor.lastrowid)


def _touch_conversation(conversation_id: int, conn: sqlite3.Connection) -> None:
    """Update conversation updated timestamp inside existing transaction."""
    conn.execute(
        "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (conversation_id,),
    )


def add_message(conversation_id: int, role: str, content: str) -> int:
    """Persist one chat message."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, role, content),
        )
        _touch_conversation(conversation_id, conn)
        return int(cursor.lastrowid)


def get_messages(conversation_id: int) -> list[dict[str, Any]]:
    """Return all messages for one conversation."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_lead(conversation_id: int) -> Optional[dict[str, Any]]:
    """Return one structured lead object for conversation."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE conversation_id = ? LIMIT 1",
            (conversation_id,),
        ).fetchone()

    if not row:
        return None

    lead = dict(row)
    return {field: lead.get(field, "") or "" for field in LEAD_FIELDS}


def upsert_lead(conversation_id: int, clinic_id: int, lead: dict[str, Any]) -> int:
    """Insert/update lead for conversation and return lead id."""
    payload = {field: (lead.get(field) or "") for field in LEAD_FIELDS}

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM leads WHERE conversation_id = ? LIMIT 1",
            (conversation_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE leads
                SET treatment_interest = ?, booking_type = ?, preferred_date = ?, preferred_time = ?,
                    timeframe = ?, name = ?, phone = ?, email = ?, notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE conversation_id = ?
                """,
                (
                    payload["treatment_interest"],
                    payload["booking_type"],
                    payload["preferred_date"],
                    payload["preferred_time"],
                    payload["timeframe"],
                    payload["name"],
                    payload["phone"],
                    payload["email"],
                    payload["notes"],
                    conversation_id,
                ),
            )
            lead_id = int(existing["id"])
        else:
            cursor = conn.execute(
                """
                INSERT INTO leads (
                    conversation_id,
                    clinic_id,
                    treatment_interest,
                    booking_type,
                    preferred_date,
                    preferred_time,
                    timeframe,
                    name,
                    phone,
                    email,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    clinic_id,
                    payload["treatment_interest"],
                    payload["booking_type"],
                    payload["preferred_date"],
                    payload["preferred_time"],
                    payload["timeframe"],
                    payload["name"],
                    payload["phone"],
                    payload["email"],
                    payload["notes"],
                ),
            )
            lead_id = int(cursor.lastrowid)

        _touch_conversation(conversation_id, conn)
        return lead_id


def get_booking_for_conversation(conversation_id: int) -> Optional[dict[str, Any]]:
    """Return booking result for one conversation if present."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE conversation_id = ? LIMIT 1",
            (conversation_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_booking_for_conversation(conversation_id: int) -> None:
    """Delete booking outcome for a conversation (used to clear stale pending rows)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM bookings WHERE conversation_id = ?", (conversation_id,))


def upsert_booking(
    conversation_id: int,
    clinic_id: int,
    lead_id: Optional[int],
    booking_payload: dict[str, Any],
) -> int:
    """Insert/update booking row and return booking id."""
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM bookings WHERE conversation_id = ? LIMIT 1",
            (conversation_id,),
        ).fetchone()

        payload = {
            "treatment_interest": booking_payload.get("treatment_interest", ""),
            "booking_type": booking_payload.get("booking_type", ""),
            "preferred_date": booking_payload.get("preferred_date", ""),
            "preferred_time": booking_payload.get("preferred_time", ""),
            "duration_minutes": int(booking_payload.get("duration_minutes") or 30),
            "status": booking_payload.get("status", "booking_request"),
            "outcome_reason": booking_payload.get("outcome_reason", "incomplete_details"),
            "notes": booking_payload.get("notes", ""),
        }

        if existing:
            conn.execute(
                """
                UPDATE bookings
                SET clinic_id = ?, lead_id = ?, treatment_interest = ?, booking_type = ?,
                    preferred_date = ?, preferred_time = ?, duration_minutes = ?,
                    status = ?, outcome_reason = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE conversation_id = ?
                """,
                (
                    clinic_id,
                    lead_id,
                    payload["treatment_interest"],
                    payload["booking_type"],
                    payload["preferred_date"],
                    payload["preferred_time"],
                    payload["duration_minutes"],
                    payload["status"],
                    payload["outcome_reason"],
                    payload["notes"],
                    conversation_id,
                ),
            )
            booking_id = int(existing["id"])
        else:
            cursor = conn.execute(
                """
                INSERT INTO bookings (
                    conversation_id,
                    clinic_id,
                    lead_id,
                    treatment_interest,
                    booking_type,
                    preferred_date,
                    preferred_time,
                    duration_minutes,
                    status,
                    outcome_reason,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    clinic_id,
                    lead_id,
                    payload["treatment_interest"],
                    payload["booking_type"],
                    payload["preferred_date"],
                    payload["preferred_time"],
                    payload["duration_minutes"],
                    payload["status"],
                    payload["outcome_reason"],
                    payload["notes"],
                ),
            )
            booking_id = int(cursor.lastrowid)

        _touch_conversation(conversation_id, conn)
        return booking_id


def get_confirmed_bookings_for_date(
    clinic_id: int,
    date_iso: str,
    exclude_conversation_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Return confirmed bookings for one clinic day, sorted by time."""
    sql = """
        SELECT id, conversation_id, preferred_date, preferred_time, duration_minutes, treatment_interest
        FROM bookings
        WHERE clinic_id = ?
          AND preferred_date = ?
          AND status = 'confirmed'
    """
    params: list[Any] = [clinic_id, date_iso]

    if exclude_conversation_id is not None:
        sql += " AND conversation_id != ?"
        params.append(exclude_conversation_id)

    sql += " ORDER BY preferred_time ASC"

    with get_connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def list_leads(limit: int = 400) -> list[dict[str, Any]]:
    """List latest leads for admin table."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                l.id,
                l.conversation_id,
                l.treatment_interest,
                l.booking_type,
                l.preferred_date,
                l.preferred_time,
                l.timeframe,
                l.name,
                l.phone,
                l.email,
                l.notes,
                l.created_at,
                l.updated_at
            FROM leads l
            ORDER BY l.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_bookings(status: Optional[str] = None, limit: int = 400) -> list[dict[str, Any]]:
    """List latest bookings, optionally filtered by status."""
    sql = """
        SELECT
            b.id,
            b.conversation_id,
            b.status,
            b.outcome_reason,
            b.treatment_interest,
            b.booking_type,
            b.preferred_date,
            b.preferred_time,
            b.duration_minutes,
            b.notes,
            b.created_at,
            b.updated_at,
            l.name,
            l.phone,
            l.email
        FROM bookings b
        LEFT JOIN leads l ON b.lead_id = l.id
    """

    params: list[Any] = []
    if status:
        sql += " WHERE b.status = ?"
        params.append(status)

    sql += " ORDER BY b.updated_at DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    return [dict(row) for row in rows]


def list_conversations(limit: int = 400) -> list[dict[str, Any]]:
    """List conversations with message count and latest message preview."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id,
                c.started_at,
                c.updated_at,
                COUNT(m.id) AS message_count,
                COALESCE(
                    (
                        SELECT mm.content
                        FROM messages mm
                        WHERE mm.conversation_id = c.id
                        ORDER BY mm.id DESC
                        LIMIT 1
                    ),
                    ''
                ) AS last_message
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]
