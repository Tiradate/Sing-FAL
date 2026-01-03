from collections import defaultdict
from datetime import datetime, timedelta
import re
import sqlite3

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

MILESIGHT_METRIC_ALIASES = {
    "temp": "temperature",
    "temperature": "temperature",
    "humidity": "humidity",
    "co2": "co2",
    "pm2_5": "pm25",
    "pm2.5": "pm25",
    "pm25": "pm25",
    "pm10": "pm10",
    "tvoc": "tvoc",
}


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


def update_device_position(device_id, location_x, location_y):
    with connect(SENSOR_DB) as conn:
        conn.execute(
            "UPDATE devices SET location_x = ?, location_y = ? WHERE device_id = ?",
            (location_x, location_y, device_id),
        )


def update_device_layout(device_id, floor_id, location_x, location_y):
    with connect(SENSOR_DB) as conn:
        conn.execute(
            "UPDATE devices SET floor_id = ?, location_x = ?, location_y = ? WHERE device_id = ?",
            (floor_id, location_x, location_y, device_id),
        )


def _slugify_identifier(value, default="device"):
    cleaned = re.sub(r"\s+", "-", str(value or "").strip())
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", cleaned)
    return cleaned or default


def _next_device_id(conn, floor_id):
    base = _slugify_identifier(floor_id)
    rows = conn.execute(
        "SELECT device_id FROM devices WHERE device_id LIKE ?",
        (f"{base}-%",),
    ).fetchall()
    max_suffix = 0
    for row in rows:
        device_id = row["device_id"]
        suffix = device_id[len(base) + 1 :]
        if suffix.isdigit():
            max_suffix = max(max_suffix, int(suffix))
    candidate = f"{base}-{max_suffix + 1}"
    while conn.execute(
        "SELECT 1 FROM devices WHERE device_id = ?",
        (candidate,),
    ).fetchone():
        max_suffix += 1
        candidate = f"{base}-{max_suffix + 1}"
    return candidate


def _normalize_metric_key(metric):
    if not metric:
        return None
    key = str(metric).strip().lower()
    return MILESIGHT_METRIC_ALIASES.get(key)


def _normalize_timestamp(value):
    if not value:
        return datetime.utcnow().isoformat()
    if isinstance(value, (int, float)):
        epoch = float(value)
        if epoch > 1e12:
            epoch /= 1000
        return datetime.utcfromtimestamp(epoch).isoformat()
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(cleaned).isoformat()
        except ValueError:
            try:
                epoch = float(cleaned)
                if epoch > 1e12:
                    epoch /= 1000
                return datetime.utcfromtimestamp(epoch).isoformat()
            except ValueError:
                return datetime.utcnow().isoformat()
    return datetime.utcnow().isoformat()


def ingest_milesight_payload(payload, *, conn=None):
    readings = payload
    if isinstance(payload, dict):
        readings = (
            payload.get("readings")
            or payload.get("records")
            or payload.get("devices")
            or []
        )
    if not isinstance(readings, list):
        return {"error": "Payload must include a list of readings"}

    owns_conn = conn is None
    if owns_conn:
        conn = connect(SENSOR_DB)

    try:
        inserted = 0
        created = 0
        insert_rows = []
        for reading in readings:
            if not isinstance(reading, dict):
                continue
            floor_id = (reading.get("floor_id") or reading.get("floor") or "").strip()
            device_id = (reading.get("device_id") or reading.get("device") or "").strip()
            if not device_id:
                device_id = reading.get("device_eui") or reading.get("dev_eui") or ""
                device_id = str(device_id).strip()
            if not device_id or not floor_id:
                continue

            model = reading.get("model") or "Milesight AM30x"
            zone = reading.get("zone") or "Unassigned"
            location_x = reading.get("location_x")
            location_y = reading.get("location_y")
            if location_x is None:
                location_x = 50
            if location_y is None:
                location_y = 50
            signal_quality = reading.get("signal_quality")
            if signal_quality is None:
                signal_quality = 100
            ts = _normalize_timestamp(reading.get("ts") or reading.get("timestamp"))
            conn.execute(
                """
                INSERT INTO devices (
                    device_id, model, floor_id, zone, location_x, location_y, last_seen, signal_quality
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    model = excluded.model,
                    floor_id = excluded.floor_id,
                    zone = excluded.zone,
                    location_x = excluded.location_x,
                    location_y = excluded.location_y,
                    last_seen = excluded.last_seen,
                    signal_quality = excluded.signal_quality
                """,
                (
                    device_id,
                    model,
                    floor_id,
                    zone,
                    location_x,
                    location_y,
                    ts,
                    signal_quality,
                ),
            )

            topic = (reading.get("topic") or "Live").strip() or "Live"
            metrics = reading.get("metrics") or reading.get("data") or {}
            if isinstance(metrics, dict):
                for metric_key, raw_value in metrics.items():
                    normalized_metric = _normalize_metric_key(metric_key)
                    if not normalized_metric or normalized_metric not in SUPPORTED_METRICS:
                        continue
                    if raw_value is None:
                        continue
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        continue
                    insert_rows.append(
                        (
                            ts,
                            device_id,
                            floor_id,
                            normalized_metric,
                            round(value, 2),
                            SUPPORTED_METRICS[normalized_metric],
                            topic,
                        )
                    )
            if insert_rows:
                conn.executemany(
                    """
                    INSERT INTO sensor_readings (ts, device_id, floor_id, metric, value, unit, topic)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    insert_rows,
                )
                inserted += len(insert_rows)
                insert_rows.clear()
        if insert_rows:
            conn.executemany(
                """
                INSERT INTO sensor_readings (ts, device_id, floor_id, metric, value, unit, topic)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                insert_rows,
            )
            inserted += len(insert_rows)
        return {"inserted": inserted, "created_devices": created}
    finally:
        if owns_conn:
            conn.commit()
            conn.close()


def create_device(floor_id, location_x=50, location_y=50, zone="Unassigned"):
    now = datetime.utcnow().isoformat()
    with connect(SENSOR_DB) as conn:
        device_id = _next_device_id(conn, floor_id)
        conn.execute(
            """
            INSERT INTO devices (device_id, model, floor_id, zone, location_x, location_y, last_seen, signal_quality)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                "Milesight AM30x",
                floor_id,
                zone,
                location_x,
                location_y,
                now,
                100,
            ),
        )
    return {
        "device_id": device_id,
        "model": "Milesight AM30x",
        "floor_id": floor_id,
        "zone": zone,
        "location_x": location_x,
        "location_y": location_y,
        "last_seen": now,
        "signal_quality": 100,
    }


def delete_device(device_id):
    with connect(SENSOR_DB) as conn:
        conn.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
        conn.execute("DELETE FROM sensor_readings WHERE device_id = ?", (device_id,))
        conn.execute("DELETE FROM alarm_events WHERE device_id = ?", (device_id,))


def delete_devices_by_floor(floor_id):
    with connect(SENSOR_DB) as conn:
        conn.execute("DELETE FROM devices WHERE floor_id = ?", (floor_id,))
        conn.execute("DELETE FROM sensor_readings WHERE floor_id = ?", (floor_id,))
        conn.execute("DELETE FROM alarm_events WHERE floor_id = ?", (floor_id,))
        try:
            conn.execute("DELETE FROM action_history WHERE floor_id = ?", (floor_id,))
        except sqlite3.OperationalError as exc:
            if "no such table: action_history" not in str(exc):
                raise


def get_avg_signal_quality():
    with connect(SENSOR_DB) as conn:
        row = conn.execute("SELECT AVG(signal_quality) AS avg_signal FROM devices").fetchone()
        return round(row["avg_signal"] or 0, 1)


def get_active_alarms():
    with connect(SENSOR_DB) as conn:
        return conn.execute(
            "SELECT * FROM alarm_events WHERE active = 1 ORDER BY ts DESC"
        ).fetchall()


def get_today_alarms(date_value=None):
    if not date_value:
        date_value = datetime.utcnow().date().isoformat()
    with connect(SENSOR_DB) as conn:
        return conn.execute(
            "SELECT * FROM alarm_events WHERE date(ts) = date(?) ORDER BY ts DESC",
            (date_value,),
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


def get_sensor_time_bounds(floor_id=None):
    params = []
    floor_clause = ""
    if floor_id:
        floor_clause = "WHERE floor_id = ?"
        params.append(floor_id)
    query = f"""
        SELECT MIN(ts) AS min_ts, MAX(ts) AS max_ts
        FROM sensor_readings
        {floor_clause}
    """
    with connect(SENSOR_DB) as conn:
        row = conn.execute(query, params).fetchone()
    if not row or not row["min_ts"] or not row["max_ts"]:
        return None, None
    return datetime.fromisoformat(row["min_ts"]), datetime.fromisoformat(row["max_ts"])


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


def get_metric_severity(settings, metric, value):
    if value is None:
        return None
    levels = settings.get("severity_levels", [])
    if not levels:
        return None
    eligible_levels = []
    for level in levels:
        thresholds = level.get("thresholds", {})
        threshold = thresholds.get(metric)
        if threshold is None:
            continue
        if value <= threshold:
            return level
        eligible_levels.append(level)
    if eligible_levels:
        return eligible_levels[-1]
    return None


def aggregate_status_label(settings):
    levels = settings.get("severity_levels", [])
    if not levels:
        return "Good"
    return levels[0]["label"]
