import os
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.environ.get("ICON_DATA_DIR") or BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)

SENSOR_DB = os.path.join(DATA_DIR, "sensordata.db")
CALENDAR_DB = os.path.join(DATA_DIR, "calendar.db")
ALARM_DB = os.path.join(DATA_DIR, "alarm.db")
API_DB = os.path.join(DATA_DIR, "api.db")
AUTH_DB = os.path.join(DATA_DIR, "auth.db")


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
                label TEXT,
                sensor_types TEXT,
                location_x REAL,
                location_y REAL,
                sensor_icon TEXT,
                last_seen DATETIME,
                signal_quality INTEGER,
                source_name TEXT,
                source_device_name TEXT,
                source_device_uuid TEXT
            );
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME,
                ingested_at DATETIME,
                device_id TEXT,
                floor_id TEXT,
                metric TEXT,
                value REAL,
                raw_value TEXT,
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
        device_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(devices)").fetchall()
        }
        if "label" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN label TEXT")
        if "sensor_types" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN sensor_types TEXT")
        if "sensor_icon" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN sensor_icon TEXT")
        if "source_name" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN source_name TEXT")
        if "source_device_name" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN source_device_name TEXT")
        if "source_device_uuid" not in device_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN source_device_uuid TEXT")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sensor_readings)").fetchall()}
        if "ingested_at" not in columns:
            conn.execute("ALTER TABLE sensor_readings ADD COLUMN ingested_at DATETIME")
        if "topic" not in columns:
            conn.execute("ALTER TABLE sensor_readings ADD COLUMN topic TEXT DEFAULT 'Live'")
        if "raw_value" not in columns:
            conn.execute("ALTER TABLE sensor_readings ADD COLUMN raw_value TEXT")


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


def init_api_db():
    with connect(API_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS api_request_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME NOT NULL,
                source_name TEXT,
                request_role TEXT,
                request_name TEXT,
                request_method TEXT,
                request_path TEXT,
                request_url TEXT,
                use_auth INTEGER DEFAULT 1,
                request_headers TEXT,
                request_query TEXT,
                request_body TEXT,
                response_status TEXT,
                response_code INTEGER,
                response_payload TEXT,
                error_message TEXT
            );
            """
        )
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(api_request_history)").fetchall()
        }
        if "response_code" not in columns:
            conn.execute("ALTER TABLE api_request_history ADD COLUMN response_code INTEGER")


def init_auth_db():
    with connect(AUTH_DB) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                last_login_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS login_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts DATETIME NOT NULL,
                user_id INTEGER,
                username TEXT,
                attempted_username TEXT,
                success INTEGER NOT NULL DEFAULT 0,
                ip_address TEXT,
                location_text TEXT,
                request_method TEXT,
                request_path TEXT,
                user_agent TEXT,
                session_id TEXT
            );
            """
        )
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "full_name" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
        if "role" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
        if "is_active" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if "last_login_at" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN last_login_at DATETIME")
        history_columns = {row["name"] for row in conn.execute("PRAGMA table_info(login_history)").fetchall()}
        if "location_text" not in history_columns:
            conn.execute("ALTER TABLE login_history ADD COLUMN location_text TEXT")
        if "request_method" not in history_columns:
            conn.execute("ALTER TABLE login_history ADD COLUMN request_method TEXT")
        if "request_path" not in history_columns:
            conn.execute("ALTER TABLE login_history ADD COLUMN request_path TEXT")
        if "user_agent" not in history_columns:
            conn.execute("ALTER TABLE login_history ADD COLUMN user_agent TEXT")
        if "session_id" not in history_columns:
            conn.execute("ALTER TABLE login_history ADD COLUMN session_id TEXT")
        conn.execute("UPDATE users SET role = 'guest' WHERE role = 'user'")


def init_all():
    init_sensor_db()
    init_calendar_db()
    init_alarm_db()
    init_api_db()
    init_auth_db()


def seed_demo_data():
    with connect(CALENDAR_DB) as conn:
        today = datetime.now(timezone.utc).date().isoformat()
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
