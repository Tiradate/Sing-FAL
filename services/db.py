import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = BASE_DIR

SENSOR_DB = os.path.join(DATA_DIR, "sensordata.db")
CALENDAR_DB = os.path.join(DATA_DIR, "calendar.db")
ALARM_DB = os.path.join(DATA_DIR, "alarm.db")


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_sensor_db():
    with connect(SENSOR_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                model TEXT,
                floor_id TEXT,
                zone TEXT,
                location_x REAL,
                location_y REAL,
                last_seen DATETIME,
                signal_quality INTEGER
            );
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME,
                device_id TEXT,
                floor_id TEXT,
                metric TEXT,
                value REAL,
                unit TEXT,
                topic TEXT DEFAULT 'Live'
            );
            CREATE TABLE IF NOT EXISTS alarm_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME,
                device_id TEXT,
                floor_id TEXT,
                metric TEXT,
                value REAL,
                severity TEXT,
                message TEXT,
                active INTEGER DEFAULT 1
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sensor_readings)").fetchall()}
        if "topic" not in columns:
            conn.execute("ALTER TABLE sensor_readings ADD COLUMN topic TEXT DEFAULT 'Live'")


def init_calendar_db():
    with connect(CALENDAR_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_alarm_summary (
                date DATE PRIMARY KEY,
                total_alarm INTEGER,
                moderate_count INTEGER,
                unhealthy_count INTEGER
            );
            """
        )


def init_alarm_db():
    with connect(ALARM_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS alarm_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alarm_event_id INTEGER,
                ts DATETIME,
                device_id TEXT,
                floor_id TEXT,
                metric TEXT,
                value REAL,
                severity TEXT,
                message TEXT,
                action_owner TEXT,
                action_note TEXT
            );
            CREATE TABLE IF NOT EXISTS action_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alarm_event_id INTEGER,
                action_ts DATETIME,
                alarm_ts DATETIME,
                device_id TEXT,
                floor_id TEXT,
                metric TEXT,
                value REAL,
                severity TEXT,
                message TEXT,
                action_owner TEXT,
                action_note TEXT,
                checklist TEXT
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(alarm_history)").fetchall()}
        if "alarm_event_id" not in columns:
            conn.execute("ALTER TABLE alarm_history ADD COLUMN alarm_event_id INTEGER")
        if "action_owner" not in columns:
            conn.execute("ALTER TABLE alarm_history ADD COLUMN action_owner TEXT")
        if "action_note" not in columns:
            conn.execute("ALTER TABLE alarm_history ADD COLUMN action_note TEXT")
        action_columns = {row["name"] for row in conn.execute("PRAGMA table_info(action_history)").fetchall()}
        if "alarm_event_id" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN alarm_event_id INTEGER")
        if "action_ts" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN action_ts DATETIME")
        if "alarm_ts" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN alarm_ts DATETIME")
        if "device_id" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN device_id TEXT")
        if "floor_id" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN floor_id TEXT")
        if "metric" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN metric TEXT")
        if "value" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN value REAL")
        if "severity" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN severity TEXT")
        if "message" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN message TEXT")
        if "action_owner" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN action_owner TEXT")
        if "action_note" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN action_note TEXT")
        if "checklist" not in action_columns:
            conn.execute("ALTER TABLE action_history ADD COLUMN checklist TEXT")


def init_all():
    init_sensor_db()
    init_calendar_db()
    init_alarm_db()


def seed_demo_data():
    with connect(CALENDAR_DB) as conn:
        today = datetime.utcnow().date().isoformat()
        existing = conn.execute(
            "SELECT date FROM daily_alarm_summary WHERE date = ?", (today,)
        ).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO daily_alarm_summary (date, total_alarm, moderate_count, unhealthy_count)
                VALUES (?, ?, ?, ?)
                """,
                (today, 5, 3, 2),
            )
