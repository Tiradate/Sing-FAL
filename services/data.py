from collections import defaultdict
from datetime import datetime, timedelta

from services.db import connect, SENSOR_DB, CALENDAR_DB


SUPPORTED_METRICS = {
    "temperature": "°C",
    "humidity": "%RH",
    "co2": "ppm",
    "pm25": "µg/m³",
    "pm10": "µg/m³",
    "tvoc": "mg/m³",
    "light": "lux",
    "pressure": "hPa",
    "motion": "",
    "signal_quality": "%",
}


def get_devices():
    with connect(SENSOR_DB) as conn:
        return conn.execute("SELECT * FROM devices").fetchall()


def get_avg_signal_quality():
    with connect(SENSOR_DB) as conn:
        row = conn.execute("SELECT AVG(signal_quality) AS avg_signal FROM devices").fetchone()
        return round(row["avg_signal"] or 0, 1)


def get_active_alarms():
    with connect(SENSOR_DB) as conn:
        return conn.execute(
            "SELECT * FROM alarm_events WHERE active = 1 ORDER BY ts DESC"
        ).fetchall()


def get_alarm_count():
    with connect(SENSOR_DB) as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM alarm_events WHERE active = 1").fetchone()
        return row["total"]


def get_calendar_value():
    today = datetime.utcnow().date().isoformat()
    with connect(CALENDAR_DB) as conn:
        row = conn.execute(
            "SELECT total_alarm FROM daily_alarm_summary WHERE date = ?", (today,)
        ).fetchone()
        return row["total_alarm"] if row else 0


def get_floor_list():
    with connect(SENSOR_DB) as conn:
        rows = conn.execute("SELECT DISTINCT floor_id FROM devices ORDER BY floor_id").fetchall()
        return [row["floor_id"] for row in rows]


def get_latest_avg_metrics(floor_id=None):
    metrics = ["temperature", "pm25", "pm10", "humidity", "tvoc", "co2"]
    placeholders = ",".join(["?"] * len(metrics))
    params = metrics
    floor_clause = ""
    if floor_id:
        floor_clause = "AND floor_id = ?"
        params = metrics + [floor_id]
    query = f"""
        SELECT metric, AVG(value) AS avg_value, unit
        FROM sensor_readings
        WHERE metric IN ({placeholders}) {floor_clause}
        GROUP BY metric
    """
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(query, params).fetchall()
        return {row["metric"]: {"value": row["avg_value"], "unit": row["unit"]} for row in rows}


def get_latest_indoor_outdoor(floor_id=None):
    metrics = ["temperature", "humidity", "co2", "pm25", "pm10", "tvoc"]
    placeholders = ",".join(["?"] * len(metrics))
    params = metrics
    floor_clause = ""
    if floor_id:
        floor_clause = "AND floor_id = ?"
        params = metrics + [floor_id]
    query = f"""
        SELECT metric, AVG(value) AS avg_value, unit
        FROM sensor_readings
        WHERE metric IN ({placeholders}) {floor_clause}
        GROUP BY metric
    """
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(query, params).fetchall()
        return rows


def get_daily_series(metric="pm25", floor_id=None):
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=23)
    params = [metric, start.isoformat()]
    floor_clause = ""
    if floor_id:
        floor_clause = "AND floor_id = ?"
        params.append(floor_id)
    query = f"""
        SELECT strftime('%H:00', ts) AS hour_label, AVG(value) AS avg_value
        FROM sensor_readings
        WHERE metric = ? AND ts >= ? {floor_clause}
        GROUP BY hour_label
        ORDER BY hour_label
    """
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(query, params).fetchall()
        labels = [row["hour_label"] for row in rows]
        values = [round(row["avg_value"], 2) for row in rows]
        return labels, values


def get_weekly_series(metric="pm25", floor_id=None):
    now = datetime.utcnow().date()
    start = now - timedelta(days=6)
    params = [metric, start.isoformat()]
    floor_clause = ""
    if floor_id:
        floor_clause = "AND floor_id = ?"
        params.append(floor_id)
    query = f"""
        SELECT date(ts) AS date_label, AVG(value) AS avg_value
        FROM sensor_readings
        WHERE metric = ? AND date(ts) >= ? {floor_clause}
        GROUP BY date_label
        ORDER BY date_label
    """
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(query, params).fetchall()
        labels = [row["date_label"] for row in rows]
        values = [round(row["avg_value"], 2) for row in rows]
        return labels, values


def get_device_alarm_severity():
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(
            """
            SELECT device_id, severity, MAX(ts) AS last_ts
            FROM alarm_events
            WHERE active = 1
            GROUP BY device_id
            """
        ).fetchall()
        return {row["device_id"]: row["severity"] for row in rows}


def get_alarm_history():
    from services.db import connect, ALARM_DB

    with connect(ALARM_DB) as conn:
        return conn.execute("SELECT * FROM alarm_history ORDER BY ts DESC LIMIT 50").fetchall()


def get_sensor_readings_csv():
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(
            "SELECT ts, device_id, floor_id, metric, value, unit FROM sensor_readings ORDER BY ts DESC"
        ).fetchall()
        return rows


def aggregate_status_label(settings):
    levels = settings.get("severity_levels", [])
    if not levels:
        return "Good"
    return levels[0]["label"]
