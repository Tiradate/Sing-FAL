import os
import sqlite3
from datetime import datetime, timedelta

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
                unit TEXT
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
                action_note TEXT
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


def init_all():
    init_sensor_db()
    init_calendar_db()
    init_alarm_db()


def seed_demo_data():
    with connect(SENSOR_DB) as conn:
        device_count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        if device_count == 0:
            devices = [
                ("AM30X-001", "Milesight AM30x", "F1", "Lobby", 20, 30, datetime.utcnow(), 92),
                ("AM30X-002", "Milesight AM30x", "F1", "Office", 60, 50, datetime.utcnow(), 88),
                ("AM30X-003", "Milesight AM30x", "F2", "Meeting", 35, 70, datetime.utcnow(), 79),
            ]
            conn.executemany(
                """
                INSERT INTO devices (device_id, model, floor_id, zone, location_x, location_y, last_seen, signal_quality)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                devices,
            )

        readings_count = conn.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]
        if readings_count == 0:
            now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
            metrics = [
                ("temperature", "°C"),
                ("humidity", "%RH"),
                ("co2", "ppm"),
                ("pm25", "µg/m³"),
                ("pm10", "µg/m³"),
                ("tvoc", "mg/m³"),
                ("light", "lux"),
                ("pressure", "hPa"),
                ("motion", ""),
                ("signal_quality", "%"),
            ]
            devices = ["AM30X-001", "AM30X-002", "AM30X-003"]
            floors = {"AM30X-001": "F1", "AM30X-002": "F1", "AM30X-003": "F2"}
            rows = []
            for hour_offset in range(24):
                ts = now - timedelta(hours=hour_offset)
                for device in devices:
                    for metric, unit in metrics:
                        base = 1
                        if metric == "temperature":
                            base = 23
                        elif metric == "humidity":
                            base = 55
                        elif metric == "co2":
                            base = 650
                        elif metric == "pm25":
                            base = 12
                        elif metric == "pm10":
                            base = 24
                        elif metric == "tvoc":
                            base = 0.4
                        elif metric == "light":
                            base = 320
                        elif metric == "pressure":
                            base = 1012
                        elif metric == "motion":
                            base = 0
                        elif metric == "signal_quality":
                            base = 90
                        value = base + (hour_offset % 5) * 0.5
                        rows.append((ts.isoformat(), device, floors[device], metric, value, unit))
            conn.executemany(
                """
                INSERT INTO sensor_readings (ts, device_id, floor_id, metric, value, unit)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        alarm_count = conn.execute("SELECT COUNT(*) FROM alarm_events").fetchone()[0]
        if alarm_count == 0:
            alarms = [
                (datetime.utcnow().isoformat(), "AM30X-002", "F1", "pm25", 55, "Unhealthy", "PM2.5 above threshold", 1),
                (datetime.utcnow().isoformat(), "AM30X-003", "F2", "co2", 1200, "Moderate", "CO2 elevated", 1),
            ]
            conn.executemany(
                """
                INSERT INTO alarm_events (ts, device_id, floor_id, metric, value, severity, message, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                alarms,
            )

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

    with connect(ALARM_DB) as conn:
        history_count = conn.execute("SELECT COUNT(*) FROM alarm_history").fetchone()[0]
        if history_count == 0:
            conn.execute(
                """
                INSERT INTO alarm_history (ts, device_id, floor_id, metric, value, severity, message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.utcnow().isoformat(),
                    "AM30X-001",
                    "F1",
                    "temperature",
                    28,
                    "Moderate",
                    "Temperature elevated",
                ),
            )
