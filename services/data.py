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
}

METRIC_DISPLAY = {
    "temperature": "Temperature",
    "humidity": "Humidity",
    "co2": "CO₂",
    "pm25": "PM2.5",
    "pm10": "PM10",
    "tvoc": "TVOC",
}

METRIC_ORDER = [
    "temperature",
    "humidity",
    "co2",
    "pm25",
    "pm10",
    "tvoc",
]


def get_metric_label(metric):
    return METRIC_DISPLAY.get(metric, metric.upper())


def get_metric_options():
    options = []
    for metric in METRIC_ORDER:
        options.append(
            {
                "key": metric,
                "label": METRIC_DISPLAY.get(metric, metric.upper()),
                "unit": SUPPORTED_METRICS.get(metric, ""),
            }
        )
    return options


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


def get_latest_device_metrics(floor_id=None):
    metrics = METRIC_ORDER
    placeholders = ",".join(["?"] * len(metrics))
    params = list(metrics)
    floor_clause = ""
    if floor_id:
        floor_clause = "AND floor_id = ?"
        params.append(floor_id)
    query = f"""
        SELECT sensor_readings.device_id,
               sensor_readings.metric,
               sensor_readings.value,
               sensor_readings.unit
        FROM sensor_readings
        JOIN (
            SELECT device_id, metric, MAX(ts) AS max_ts
            FROM sensor_readings
            WHERE metric IN ({placeholders}) {floor_clause}
            GROUP BY device_id, metric
        ) latest
        ON sensor_readings.device_id = latest.device_id
        AND sensor_readings.metric = latest.metric
        AND sensor_readings.ts = latest.max_ts
    """
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(query, params).fetchall()
    metrics_by_device = defaultdict(dict)
    for row in rows:
        metrics_by_device[row["device_id"]][row["metric"]] = {
            "value": row["value"],
            "unit": row["unit"],
        }
    return metrics_by_device


def get_latest_indoor_outdoor(floor_id=None):
    metrics = ["temperature", "humidity", "co2", "pm25", "pm10", "tvoc"]
    indoor_rows = _get_metric_avg_by_zone(metrics, floor_id=floor_id, is_outdoor=False)
    outdoor_rows = _get_metric_avg_by_zone(metrics, floor_id=floor_id, is_outdoor=True)
    rows = []
    for metric in metrics:
        indoor = indoor_rows.get(metric)
        outdoor = outdoor_rows.get(metric)
        unit = None
        if indoor and indoor.get("unit"):
            unit = indoor["unit"]
        elif outdoor and outdoor.get("unit"):
            unit = outdoor["unit"]
        else:
            unit = SUPPORTED_METRICS.get(metric, "")
        rows.append(
            {
                "metric": metric,
                "unit": unit,
                "indoor_value": indoor["avg_value"] if indoor else None,
                "outdoor_value": outdoor["avg_value"] if outdoor else None,
            }
        )
    return rows


def get_indoor_outdoor_aqi(floor_id=None):
    indoor_rows = _get_metric_avg_by_zone(["pm25"], floor_id=floor_id, is_outdoor=False)
    outdoor_rows = _get_metric_avg_by_zone(["pm25"], floor_id=floor_id, is_outdoor=True)
    return {
        "indoor": indoor_rows.get("pm25", {}).get("avg_value"),
        "outdoor": outdoor_rows.get("pm25", {}).get("avg_value"),
    }


def _get_metric_avg_by_zone(metrics, floor_id=None, is_outdoor=False):
    placeholders = ",".join(["?"] * len(metrics))
    params = list(metrics)
    floor_clause = ""
    if floor_id:
        floor_clause = "AND sensor_readings.floor_id = ?"
        params.append(floor_id)
    outdoor_clause = (
        "(lower(devices.zone) LIKE '%outdoor%' OR lower(devices.zone) LIKE '%outside%')"
    )
    if is_outdoor:
        zone_clause = f"AND {outdoor_clause}"
    else:
        zone_clause = f"AND (devices.zone IS NULL OR NOT {outdoor_clause})"
    query = f"""
        SELECT sensor_readings.metric, AVG(sensor_readings.value) AS avg_value, sensor_readings.unit
        FROM sensor_readings
        JOIN devices ON devices.device_id = sensor_readings.device_id
        WHERE sensor_readings.metric IN ({placeholders}) {floor_clause} {zone_clause}
        GROUP BY sensor_readings.metric
    """
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(query, params).fetchall()
        return {row["metric"]: {"avg_value": row["avg_value"], "unit": row["unit"]} for row in rows}


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
        return conn.execute(
            "SELECT * FROM action_history ORDER BY action_ts DESC LIMIT 50"
        ).fetchall()


def get_action_history(start_date, end_date):
    from services.db import connect, ALARM_DB

    query = """
        SELECT *
        FROM action_history
        WHERE date(action_ts) BETWEEN date(?) AND date(?)
        ORDER BY action_ts DESC
    """
    with connect(ALARM_DB) as conn:
        return conn.execute(query, (start_date, end_date)).fetchall()


def save_alarm_response(alarm_id, action_owner=None, action_note=None, checklist=None):
    from services.db import connect, ALARM_DB, SENSOR_DB

    with connect(SENSOR_DB) as conn:
        alarm = conn.execute("SELECT * FROM alarm_events WHERE id = ?", (alarm_id,)).fetchone()
        if not alarm:
            return False
        newer_alarm = conn.execute(
            """
            SELECT 1
            FROM alarm_events
            WHERE device_id = ? AND ts > ? AND active = 1
            ORDER BY ts DESC
            LIMIT 1
            """,
            (alarm["device_id"], alarm["ts"]),
        ).fetchone()
        if newer_alarm:
            return False

    with connect(ALARM_DB) as conn:
        conn.execute(
            """
            INSERT INTO action_history (
                alarm_event_id,
                action_ts,
                alarm_ts,
                device_id,
                floor_id,
                metric,
                value,
                severity,
                message,
                action_owner,
                action_note,
                checklist
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alarm_id,
                datetime.utcnow().isoformat(),
                alarm["ts"],
                alarm["device_id"],
                alarm["floor_id"],
                alarm["metric"],
                alarm["value"],
                alarm["severity"],
                alarm["message"],
                action_owner,
                action_note,
                checklist,
            ),
        )
    return True


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
