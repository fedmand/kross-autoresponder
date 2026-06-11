"""
Persistent storage for escalation notifications.

Shared between the bot (records new escalations, checks for duplicates before
re-notifying) and the host GUI (reads pending notifications, marks them
resolved). One SQLite file, no server — both sides import this module.
"""
import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "notifications.db")

# A fresh connection is opened and closed per call. SQLite connections can't
# be shared across threads, and Streamlit reruns may run on different threads,
# so each operation stays self-contained rather than holding a module-level one.


def init_db():
    # (id_thread, id_message) is the dedup key — one notification per
    # specific guest message that triggered an escalation.
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            id_thread       INTEGER NOT NULL,
            id_message      INTEGER NOT NULL,
            id_reservation  INTEGER,
            category        TEXT,
            home            TEXT,
            guest_name      TEXT,
            channel         TEXT,
            check_in        TEXT,
            check_out       TEXT,
            message         TEXT,
            summary         TEXT,
            created_at      TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            handled_by      TEXT,
            read_by         TEXT,
            UNIQUE(id_thread, id_message)
        )
    """)
    # Dedup log for messages the bot auto-replied to. Kept separate from the
    # notifications table so auto-replies never surface in the host dashboard —
    # this table exists purely so we don't re-call Claude for an already-answered
    # guest message on the next poll cycle.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS replied_messages (
            id_thread   INTEGER NOT NULL,
            id_message  INTEGER NOT NULL,
            replied_at  TEXT NOT NULL,
            UNIQUE(id_thread, id_message)
        )
    """)
    # Per-thread "last fully handled" marker. We store the last_update value
    # (from get-threads) that we processed without error. On the next poll, if
    # a thread's last_update is unchanged, nothing new happened and we can skip
    # the expensive get-thread call entirely. This stops Kross's permanently
    # to_read threads (host replied via Airbnb/Booking, which never clears
    # to_read) from burning a get-thread call every single cycle.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thread_state (
            id_thread    INTEGER PRIMARY KEY,
            last_update  TEXT,
            seen_at      TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def notification_exists(id_thread, id_message):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT 1 FROM notifications WHERE id_thread = ? AND id_message = ?",
        (id_thread, id_message),
    ).fetchone()
    conn.close()
    return row is not None


def reply_exists(id_thread, id_message):
    # True if the bot already auto-replied to this specific guest message.
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT 1 FROM replied_messages WHERE id_thread = ? AND id_message = ?",
        (id_thread, id_message),
    ).fetchone()
    conn.close()
    return row is not None


def record_reply(id_thread, id_message):
    # Mark a guest message as answered so we don't re-call Claude for it next cycle.
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO replied_messages (id_thread, id_message, replied_at) "
            "VALUES (?, ?, ?)",
            (id_thread, id_message, time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()


def get_thread_last_seen(id_thread):
    # Returns the last_update value we last fully handled for this thread, or
    # None if we've never processed it.
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT last_update FROM thread_state WHERE id_thread = ?",
        (id_thread,),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def record_thread_seen(id_thread, last_update):
    # Upsert the last_update we've fully handled for this thread, so an
    # unchanged thread is skipped (no get-thread call) on the next cycle.
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO thread_state (id_thread, last_update, seen_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(id_thread) DO UPDATE SET last_update = excluded.last_update, "
            "seen_at = excluded.seen_at",
            (id_thread, last_update, time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()


def record_notification(notification):
    # notification: dict with keys matching the table columns, minus
    # created_at/status/handled_by/read_by, which are set here.
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT INTO notifications (
                id_thread, id_message, id_reservation, category, home,
                guest_name, channel, check_in, check_out,
                message, summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            notification["id_thread"], notification["id_message"], notification["id_reservation"],
            notification["category"], notification["home"], notification["guest_name"],
            notification["channel"], notification["check_in"], notification["check_out"],
            notification["message"], notification["summary"],
            time.strftime("%Y-%m-%d %H:%M:%S"),
        ))
        conn.commit()
    finally:
        conn.close()


def mark_resolved(notification_id, handled_by=None):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "UPDATE notifications SET status = 'resolved', handled_by = ? WHERE id = ?",
            (handled_by, notification_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_pending_notifications():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM notifications WHERE status = 'pending' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
