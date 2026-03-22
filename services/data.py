from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import re
import sqlite3
from zoneinfo import ZoneInfo

from services import settings as settings_service
from services.db import connect, SENSOR_DB, CALENDAR_DB

SERIES_TIMEZONE_FALLBACKS = {
    "UTC": timezone.utc,
    "Asia/Bangkok": timezone(timedelta(hours=7)),
    "Asia/Yangon": timezone(timedelta(hours=6, minutes=30)),
    "Asia/Singapore": timezone(timedelta(hours=8)),
    "Asia/Tokyo": timezone(timedelta(hours=9)),
    "Europe/London": timezone.utc,
    "America/New_York": timezone(timedelta(hours=-5)),
    "America/Los_Angeles": timezone(timedelta(hours=-8)),
}


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

SOURCE_METRIC_UNITS = {
    **SUPPORTED_METRICS,
    "atmospheric_pressure": "hPa",
    "battery": "%",
    "illuminance": "lux",
    "rssi": "dBm",
    "snr": "dB",
}

FIRE_DETECTOR_FIELDS = [
    ("smoke", "Smoke"),
    ("heat", "Heat"),
    ("flow_switch", "Flow Switch"),
    ("supervisory_valve", "Supervisory valve"),
    ("manual", "Manual"),
    ("gas", "Gas"),
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


def get_fire_metric_options():
    return [{"key": key, "label": label, "unit": ""} for key, label in FIRE_DETECTOR_FIELDS]


def _normalize_source_metric_field_key(metric):
    if not metric:
        return ""
    key = str(metric).strip().lower()
    return MILESIGHT_METRIC_ALIASES.get(key, key)


def _default_source_metric_label(metric):
    normalized_metric = _normalize_source_metric_field_key(metric)
    if not normalized_metric:
        return ""
    if normalized_metric in METRIC_DISPLAY:
        return METRIC_DISPLAY[normalized_metric]
    return normalized_metric.replace("_", " ").strip().title()


def normalize_device_sensor_types(sensor_types):
    if isinstance(sensor_types, str):
        raw_values = re.split(r"[,;\n]+", sensor_types)
    elif isinstance(sensor_types, (list, tuple, set)):
        raw_values = sensor_types
    else:
        raw_values = []

    normalized = []
    seen = set()
    for value in raw_values:
        key = _normalize_source_metric_field_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def serialize_device_sensor_types(sensor_types):
    normalized = normalize_device_sensor_types(sensor_types)
    return json.dumps(normalized) if normalized else None


def parse_device_sensor_types(sensor_types):
    if not sensor_types:
        return []
    if isinstance(sensor_types, str):
        try:
            loaded = json.loads(sensor_types)
        except (TypeError, ValueError, json.JSONDecodeError):
            loaded = sensor_types
        return normalize_device_sensor_types(loaded)
    return normalize_device_sensor_types(sensor_types)


def get_source_metric_fields(settings):
    raw_fields = settings.get("source_metric_fields")
    if not isinstance(raw_fields, list):
        return []

    normalized_fields = []
    for item in raw_fields:
        if not isinstance(item, dict):
            continue
        key = _normalize_source_metric_field_key(item.get("key") or item.get("field"))
        if not key:
            continue
        source_field = str(item.get("source_field") or item.get("field") or key).strip() or key
        normalized_fields.append(
            {
                "key": key,
                "source_field": source_field,
                "label": str(item.get("label") or _default_source_metric_label(source_field)).strip()
                or _default_source_metric_label(source_field),
                "channel": str(item.get("channel") or "").strip(),
                "unit": str(item.get("unit") or SOURCE_METRIC_UNITS.get(key, "")).strip(),
                "show_in_bulk_type": bool(item.get("show_in_bulk_type", True)),
                "show_in_tooltip": bool(item.get("show_in_tooltip", key in METRIC_DISPLAY)),
                "save_to_db": bool(item.get("save_to_db", key in METRIC_DISPLAY)),
                "enable_severity": bool(item.get("enable_severity", key in METRIC_DISPLAY)),
                "sources": sorted(
                    {
                        str(value).strip()
                        for value in (item.get("sources") or [])
                        if str(value).strip()
                    }
                ),
            }
        )
    return sorted(normalized_fields, key=lambda item: item["label"].lower())


def sync_source_metric_fields(settings, source_name, latest_values_payload):
    raw_fields = get_source_metric_fields(settings)
    fields_by_key = {item["key"]: dict(item) for item in raw_fields}
    latest_items = latest_values_payload.get("items") if isinstance(latest_values_payload, dict) else []
    if not isinstance(latest_items, list):
        latest_items = []

    updated = False
    for item in latest_items:
        values = item.get("values") if isinstance(item, dict) else []
        if not isinstance(values, list):
            continue
        for entry in values:
            if not isinstance(entry, dict):
                continue
            source_field = str(entry.get("field") or "").strip()
            if not source_field:
                continue
            key = _normalize_source_metric_field_key(source_field)
            if not key:
                continue
            existing = fields_by_key.get(key)
            if not existing:
                existing = {
                    "key": key,
                    "source_field": source_field,
                    "label": _default_source_metric_label(source_field),
                    "channel": str(entry.get("channel") or "").strip(),
                    "unit": SOURCE_METRIC_UNITS.get(key, ""),
                    "show_in_bulk_type": True,
                    "show_in_tooltip": key in METRIC_DISPLAY,
                    "save_to_db": key in METRIC_DISPLAY,
                    "enable_severity": key in METRIC_DISPLAY,
                    "sources": [],
                }
                fields_by_key[key] = existing
                updated = True
            if source_name and source_name not in existing.get("sources", []):
                existing.setdefault("sources", []).append(source_name)
                existing["sources"] = sorted({value for value in existing["sources"] if value})
                updated = True
            channel = str(entry.get("channel") or "").strip()
            if channel and not existing.get("channel"):
                existing["channel"] = channel
                updated = True
            if source_field and not existing.get("source_field"):
                existing["source_field"] = source_field
                updated = True

    normalized_fields = sorted(fields_by_key.values(), key=lambda item: item.get("label", "").lower())
    if updated or settings.get("source_metric_fields") != normalized_fields:
        settings["source_metric_fields"] = normalized_fields
        return True
    return False


def get_tooltip_metric_options(settings):
    source_fields = get_source_metric_fields(settings)
    if not source_fields:
        return get_metric_options()

    source_field_map = {field["key"]: field for field in source_fields}
    options = []
    existing_keys = set()

    for metric in METRIC_ORDER:
        field = source_field_map.get(metric)
        if field:
            existing_keys.add(metric)
            if not field.get("show_in_tooltip"):
                continue
            options.append(
                {
                    "key": metric,
                    "label": field.get("label") or METRIC_DISPLAY.get(metric, metric.upper()),
                    "unit": field.get("unit") or SUPPORTED_METRICS.get(metric, ""),
                }
            )
            continue
        options.append(
            {
                "key": metric,
                "label": METRIC_DISPLAY.get(metric, metric.upper()),
                "unit": SUPPORTED_METRICS.get(metric, ""),
            }
        )
        existing_keys.add(metric)

    for field in source_fields:
        if not field.get("show_in_tooltip"):
            continue
        if field["key"] in existing_keys:
            continue
        options.append(
            {
                "key": field["key"],
                "label": field.get("label") or _default_source_metric_label(field["key"]),
                "unit": field.get("unit", ""),
            }
        )
        existing_keys.add(field["key"])

    return options


def get_devices():
    with connect(SENSOR_DB) as conn:
        rows = conn.execute("SELECT * FROM devices").fetchall()
    devices = []
    for row in rows:
        device = dict(row)
        device["sensor_types"] = parse_device_sensor_types(device.get("sensor_types"))
        devices.append(device)
    return devices


def update_device_position(device_id, location_x, location_y):
    with connect(SENSOR_DB) as conn:
        conn.execute(
            "UPDATE devices SET location_x = ?, location_y = ? WHERE device_id = ?",
            (location_x, location_y, device_id),
        )


def update_device_zone(device_id, zone):
    with connect(SENSOR_DB) as conn:
        conn.execute(
            "UPDATE devices SET zone = ? WHERE device_id = ?",
            (zone, device_id),
        )


def update_device_source_mapping(
    device_id,
    source_name=None,
    source_device_name=None,
    source_device_uuid=None,
):
    with connect(SENSOR_DB) as conn:
        conn.execute(
            """
            UPDATE devices
            SET source_name = ?, source_device_name = ?, source_device_uuid = ?
            WHERE device_id = ?
            """,
            (source_name, source_device_name, source_device_uuid, device_id),
        )


def update_device_sensor_types(device_id, sensor_types):
    with connect(SENSOR_DB) as conn:
        conn.execute(
            "UPDATE devices SET sensor_types = ? WHERE device_id = ?",
            (serialize_device_sensor_types(sensor_types), device_id),
        )


def update_device_label(device_id, label):
    with connect(SENSOR_DB) as conn:
        conn.execute(
            "UPDATE devices SET label = ? WHERE device_id = ?",
            (label, device_id),
        )


def update_device_layout(device_id, floor_id, location_x, location_y):
    with connect(SENSOR_DB) as conn:
        conn.execute(
            "UPDATE devices SET floor_id = ?, location_x = ?, location_y = ? WHERE device_id = ?",
            (floor_id, location_x, location_y, device_id),
        )


def upsert_device_layouts(layouts):
    now = datetime.now(timezone.utc).isoformat()
    with connect(SENSOR_DB) as conn:
        for layout in layouts:
            device_id = (layout.get("device_id") or "").strip()
            if not device_id:
                continue
            floor_id = (layout.get("floor_id") or "").strip()
            location_x = layout.get("location_x")
            location_y = layout.get("location_y")
            source_name = (layout.get("source_name") or "").strip() or None
            source_device_name = (
                (layout.get("source_device_name") or "").strip() or None
            )
            source_device_uuid = (
                (layout.get("source_device_uuid") or "").strip() or None
            )
            conn.execute(
                """
                INSERT INTO devices (
                    device_id,
                    model,
                    floor_id,
                    zone,
                    label,
                    sensor_types,
                    location_x,
                    location_y,
                    sensor_icon,
                    last_seen,
                    signal_quality,
                    source_name,
                    source_device_name,
                    source_device_uuid
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id)
                DO UPDATE SET
                    floor_id = excluded.floor_id,
                    location_x = excluded.location_x,
                    location_y = excluded.location_y,
                    source_name = COALESCE(excluded.source_name, devices.source_name),
                    source_device_name = COALESCE(
                        excluded.source_device_name,
                        devices.source_device_name
                    ),
                    source_device_uuid = COALESCE(
                        excluded.source_device_uuid,
                        devices.source_device_uuid
                    )
                """,
                (
                    device_id,
                    "Milesight AM30x",
                    floor_id,
                    "Z1",
                    None,
                    None,
                    location_x,
                    location_y,
                    None,
                    now,
                    100,
                    source_name,
                    source_device_name,
                    source_device_uuid,
                ),
            )


def set_sensor_icon_for_missing(default_icon):
    if not default_icon:
        return
    with connect(SENSOR_DB) as conn:
        conn.execute(
            """
            UPDATE devices
            SET sensor_icon = ?
            WHERE sensor_icon IS NULL OR sensor_icon = ''
            """,
            (default_icon,),
        )


def _slugify_identifier(value, default="device"):
    cleaned = re.sub(r"\s+", "-", str(value or "").strip())
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", cleaned)
    return cleaned or default


def _normalize_device_component(value, default):
    normalized = _slugify_identifier(value, default=default)
    return normalized.upper()


def _build_device_base(floor_id, zone=None, sensor_type=None, sensor_name=None):
    floor_slug = _normalize_device_component(floor_id, default="FLOOR")
    sensor_slug = _slugify_identifier(sensor_name, default="")
    if sensor_slug:
        return f"{floor_slug}-{sensor_slug.upper()}"
    return floor_slug


def _next_device_id(conn, base):
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


def _format_metric_value(value, unit):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value}{unit}"


def _build_alarm_message(metric, value, threshold, unit):
    metric_label = get_metric_label(metric)
    value_label = _format_metric_value(value, unit)
    threshold_label = _format_metric_value(threshold, unit) if threshold is not None else ""
    if threshold_label:
        return f"{metric_label} {value_label} exceeds {threshold_label}"
    return f"{metric_label} {value_label} is above the limit"


def _parse_fire_tokens(value):
    if not value:
        return []
    raw_tokens = re.split(r"[,;\n]+", str(value))
    return [token.strip() for token in raw_tokens if token.strip()]


def _extract_fire_text(reading):
    candidates = []
    for key in (
        "alarm_text",
        "alarm",
        "event",
        "message",
        "status",
        "raw",
        "raw_text",
        "payload",
        "tag",
        "zone",
        "device_id",
        "device",
    ):
        value = reading.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    metrics = reading.get("metrics") or reading.get("data") or {}
    if isinstance(metrics, dict):
        for value in metrics.values():
            if isinstance(value, str) and value.strip():
                candidates.append(value)
    return " ".join(candidates)


def _find_fire_matches(fire_mapping, fire_text):
    if not fire_mapping or not fire_text:
        return []
    matches = []
    haystack = fire_text.upper()
    for row in fire_mapping:
        severity_label = (row.get("label") or row.get("severity") or "").strip()
        if not severity_label:
            continue
        for detector_key, detector_label in FIRE_DETECTOR_FIELDS:
            tokens = _parse_fire_tokens(row.get(detector_key))
            for token in tokens:
                if token.upper() in haystack:
                    matches.append(
                        {
                            "severity": severity_label,
                            "metric": detector_key,
                            "message": f"{detector_label}: {token}",
                        }
                    )
                    break
    return matches


def _upsert_alarm_event(conn, *, ts, device_id, floor_id, metric, value, severity, message):
    existing_alarm = conn.execute(
        """
        SELECT id
        FROM alarm_events
        WHERE device_id = ? AND metric = ? AND active = 1
        ORDER BY ts DESC
        LIMIT 1
        """,
        (device_id, metric),
    ).fetchone()
    if existing_alarm:
        conn.execute(
            """
            UPDATE alarm_events
            SET ts = ?, floor_id = ?, value = ?, severity = ?, message = ?
            WHERE id = ?
            """,
            (
                ts,
                floor_id,
                value,
                severity,
                message,
                existing_alarm["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO alarm_events (
                ts, device_id, floor_id, metric, value, severity, message, active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                ts,
                device_id,
                floor_id,
                metric,
                value,
                severity,
                message,
            ),
        )


def _normalize_timestamp(value):
    if not value:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        epoch = float(value)
        if epoch > 1e12:
            epoch /= 1000
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
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
                return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
            except ValueError:
                return datetime.now(timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


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
    settings = settings_service.load_settings()
    critical_levels = {
        str(level) for level in settings.get("critical_levels", []) if level
    }
    if owns_conn:
        conn = connect(SENSOR_DB)
    ingestion_ts = datetime.now(timezone.utc).isoformat()
    device_rows = conn.execute("SELECT * FROM devices").fetchall()
    known_devices = {row["device_id"]: row for row in device_rows}
    mapped_source_devices = {}
    mapped_source_device_uuids = {}
    source_name_counts = {}
    for row in device_rows:
        source_name = (row["source_name"] or "").strip()
        source_device_name = (row["source_device_name"] or "").strip()
        source_device_uuid = (row["source_device_uuid"] or "").strip()
        if source_device_name:
            mapped_source_devices[(source_name, source_device_name)] = row
            source_name_counts[source_device_name] = source_name_counts.get(source_device_name, 0) + 1
        if source_device_uuid:
            mapped_source_device_uuids[(source_name, source_device_uuid)] = row
    allowed_floors = set(settings.get("floor_plans", {}).keys())

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
            source_name = (reading.get("source_name") or reading.get("source") or "").strip()
            if not device_id:
                continue
            device_row = known_devices.get(device_id)
            if not device_row:
                device_row = mapped_source_device_uuids.get((source_name, device_id))
            if not device_row:
                device_row = mapped_source_devices.get((source_name, device_id))
                if not device_row and source_name_counts.get(device_id) == 1:
                    device_row = next(
                        (
                            row
                            for (mapped_source_name, mapped_device_name), row in mapped_source_devices.items()
                            if mapped_device_name == device_id
                        ),
                        None,
                    )
            if not device_row:
                continue
            device_id = device_row["device_id"]
            stored_floor_id = (device_row["floor_id"] or "").strip()
            if not stored_floor_id:
                continue
            if allowed_floors and stored_floor_id not in allowed_floors:
                continue
            floor_id = stored_floor_id

            model = reading.get("model") or "Milesight AM30x"
            signal_quality = reading.get("signal_quality")
            if signal_quality is None:
                signal_quality = 100
            ts = _normalize_timestamp(reading.get("ts") or reading.get("timestamp"))
            conn.execute(
                """
                UPDATE devices
                SET model = ?, last_seen = ?, signal_quality = ?
                WHERE device_id = ?
                """,
                (
                    model,
                    ts,
                    signal_quality,
                    device_id,
                ),
            )

            fire_text = _extract_fire_text(reading)
            fire_matches = _find_fire_matches(
                settings.get("fire_severity_mapping", []),
                fire_text,
            )
            for match in fire_matches:
                _upsert_alarm_event(
                    conn,
                    ts=ts,
                    device_id=device_id,
                    floor_id=floor_id,
                    metric=match["metric"],
                    value=None,
                    severity=match["severity"],
                    message=match["message"],
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
                    severity = get_metric_severity(settings, normalized_metric, value)
                    severity_label = severity["label"] if severity else None
                    insert_rows.append(
                        (
                            ts,
                            ingestion_ts,
                            device_id,
                            floor_id,
                            normalized_metric,
                            round(value, 2),
                            str(raw_value),
                            SUPPORTED_METRICS[normalized_metric],
                            topic,
                        )
                    )
                    if severity_label and severity_label in critical_levels:
                        threshold = severity.get("thresholds", {}).get(normalized_metric)
                        unit = SUPPORTED_METRICS.get(normalized_metric, "")
                        message = _build_alarm_message(
                            normalized_metric, round(value, 2), threshold, unit
                        )
                        _upsert_alarm_event(
                            conn,
                            ts=ts,
                            device_id=device_id,
                            floor_id=floor_id,
                            metric=normalized_metric,
                            value=round(value, 2),
                            severity=severity_label,
                            message=message,
                        )
                    else:
                        conn.execute(
                            """
                            UPDATE alarm_events
                            SET active = 0
                            WHERE device_id = ? AND metric = ? AND active = 1
                            """,
                            (device_id, normalized_metric),
                        )
            if insert_rows:
                conn.executemany(
                    """
                    INSERT INTO sensor_readings (ts, ingested_at, device_id, floor_id, metric, value, raw_value, unit, topic)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    insert_rows,
                )
                inserted += len(insert_rows)
                insert_rows.clear()
        if insert_rows:
            conn.executemany(
                """
                INSERT INTO sensor_readings (ts, ingested_at, device_id, floor_id, metric, value, raw_value, unit, topic)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                insert_rows,
            )
            inserted += len(insert_rows)
        return {"inserted": inserted, "created_devices": created}
    finally:
        if owns_conn:
            conn.commit()
            conn.close()


def ingest_source_latest_values_payload(payload, source_name=None, *, conn=None):
    latest_items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(latest_items, list):
        return {"error": "Payload must include a list of latest value items"}

    owns_conn = conn is None
    settings = settings_service.load_settings()
    field_configs = {
        field["key"]: field
        for field in get_source_metric_fields(settings)
        if field.get("save_to_db")
    }
    if not field_configs:
        return {"inserted": 0, "matched_devices": 0}

    critical_levels = {
        str(level) for level in settings.get("critical_levels", []) if level
    }
    if owns_conn:
        conn = connect(SENSOR_DB)
    ingestion_ts = datetime.now(timezone.utc).isoformat()

    device_rows = conn.execute("SELECT * FROM devices").fetchall()
    mapped_by_uuid = {}
    mapped_by_name = {}
    for row in device_rows:
        mapped_source_name = (row["source_name"] or "").strip()
        source_device_uuid = (row["source_device_uuid"] or "").strip()
        source_device_name = (row["source_device_name"] or "").strip()
        if source_device_uuid:
            mapped_by_uuid[(mapped_source_name, source_device_uuid)] = row
        if source_device_name:
            mapped_by_name[(mapped_source_name, source_device_name)] = row

    def item_device_names(item):
        if not isinstance(item, dict):
            return []
        nested_device = item.get("device")
        candidates = [
            item.get("display_name"),
            item.get("name"),
            item.get("device_name"),
            item.get("label"),
        ]
        if isinstance(nested_device, dict):
            candidates.extend(
                [
                    nested_device.get("display_name"),
                    nested_device.get("name"),
                    nested_device.get("device_name"),
                    nested_device.get("label"),
                ]
            )
        seen = set()
        names = []
        for value in candidates:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(text)
        return names

    inserted = 0
    matched_devices = 0
    try:
        for item in latest_items:
            if not isinstance(item, dict):
                continue
            device_uuid = str(
                item.get("device_uuid")
                or item.get("uuid")
                or item.get("device_id")
                or item.get("id")
                or ""
            ).strip()
            if not device_uuid:
                continue
            device_row = mapped_by_uuid.get((str(source_name or "").strip(), device_uuid))
            if not device_row:
                candidate_names = item_device_names(item) + [device_uuid]
                for candidate_name in candidate_names:
                    device_row = mapped_by_name.get(
                        (str(source_name or "").strip(), str(candidate_name or "").strip())
                    )
                    if device_row:
                        break
            if not device_row:
                continue
            matched_devices += 1
            values = item.get("values")
            if not isinstance(values, list):
                continue
            floor_id = (device_row["floor_id"] or "").strip()
            device_id = device_row["device_id"]
            allowed_metrics = set(parse_device_sensor_types(device_row["sensor_types"]))
            for value_item in values:
                if not isinstance(value_item, dict):
                    continue
                metric_key = _normalize_source_metric_field_key(value_item.get("field"))
                if not metric_key:
                    continue
                if allowed_metrics and metric_key not in allowed_metrics:
                    continue
                field_config = field_configs.get(metric_key)
                if not field_config:
                    continue
                raw_value = value_item.get("value")
                if raw_value in (None, ""):
                    continue
                raw_text = str(raw_value)
                try:
                    numeric_value = float(raw_value)
                except (TypeError, ValueError):
                    numeric_value = None
                ts = _normalize_timestamp(
                    value_item.get("updated_at")
                    or value_item.get("ts")
                    or item.get("updated_at")
                    or item.get("ts")
                )
                unit = field_config.get("unit") or SOURCE_METRIC_UNITS.get(metric_key, "")
                conn.execute(
                    """
                    INSERT INTO sensor_readings (ts, ingested_at, device_id, floor_id, metric, value, raw_value, unit, topic)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts,
                        ingestion_ts,
                        device_id,
                        floor_id,
                        metric_key,
                        round(numeric_value, 4) if numeric_value is not None else None,
                        raw_text,
                        unit,
                        "Live",
                    ),
                )
                inserted += 1
                conn.execute(
                    """
                    UPDATE devices
                    SET last_seen = ?, source_name = ?, source_device_uuid = ?
                    WHERE device_id = ?
                    """,
                    (
                        ts,
                        str(source_name or "").strip() or None,
                        device_uuid,
                        device_id,
                    ),
                )
                severity = get_metric_severity(settings, metric_key, numeric_value)
                severity_label = severity["label"] if severity else None
                if severity_label and severity_label in critical_levels and numeric_value is not None:
                    threshold = severity.get("thresholds", {}).get(metric_key)
                    message = _build_alarm_message(
                        metric_key,
                        round(numeric_value, 2),
                        threshold,
                        unit,
                    )
                    _upsert_alarm_event(
                        conn,
                        ts=ts,
                        device_id=device_id,
                        floor_id=floor_id,
                        metric=metric_key,
                        value=round(numeric_value, 2),
                        severity=severity_label,
                        message=message,
                    )
        return {"inserted": inserted, "matched_devices": matched_devices}
    finally:
        if owns_conn:
            conn.commit()
            conn.close()


def create_device(
    floor_id,
    location_x=50,
    location_y=50,
    zone="Z1",
    sensor_type="DZ",
    sensor_name=None,
    sensor_icon=None,
):
    now = datetime.now(timezone.utc).isoformat()
    with connect(SENSOR_DB) as conn:
        zone_value = (zone or "").strip() or "Z1"
        sensor_type_value = (sensor_type or "").strip() or "DZ"
        label_value = (sensor_name or "").strip() or None
        sensor_types_value = serialize_device_sensor_types([sensor_type_value])
        sensor_icon_value = (sensor_icon or "").strip() or None
        base = _build_device_base(
            floor_id,
            zone=zone_value,
            sensor_type=sensor_type_value,
            sensor_name=sensor_name,
        )
        device_id = _next_device_id(conn, base)
        conn.execute(
            """
            INSERT INTO devices (
                device_id,
                model,
                floor_id,
                zone,
                label,
                sensor_types,
                location_x,
                location_y,
                sensor_icon,
                last_seen,
                signal_quality,
                source_name,
                source_device_name,
                source_device_uuid
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                "Milesight AM30x",
                floor_id,
                zone_value,
                label_value,
                sensor_types_value,
                location_x,
                location_y,
                sensor_icon_value,
                now,
                100,
                None,
                None,
                None,
            ),
        )
    return {
        "device_id": device_id,
        "model": "Milesight AM30x",
        "floor_id": floor_id,
        "zone": zone_value,
        "label": label_value,
        "sensor_types": parse_device_sensor_types(sensor_types_value),
        "location_x": location_x,
        "location_y": location_y,
        "sensor_icon": sensor_icon_value,
        "last_seen": now,
        "signal_quality": 100,
        "source_name": None,
        "source_device_name": None,
        "source_device_uuid": None,
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
        date_value = datetime.now(timezone.utc).date().isoformat()
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
    today = datetime.now(timezone.utc).date().isoformat()
    with connect(CALENDAR_DB) as conn:
        row = conn.execute(
            "SELECT total_alarm FROM daily_alarm_summary WHERE date = ?", (today,)
        ).fetchone()
        return row["total_alarm"] if row else 0


def get_floor_list():
    with connect(SENSOR_DB) as conn:
        rows = conn.execute("SELECT DISTINCT floor_id FROM devices ORDER BY floor_id").fetchall()
        return [row["floor_id"] for row in rows]


def get_latest_avg_metrics(floor_id=None, metrics=None):
    metrics = list(metrics or ["temperature", "pm25", "pm10", "humidity", "tvoc", "co2"])
    if not metrics:
        return {}
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


def get_latest_device_metrics(floor_id=None, metrics=None):
    metrics = list(metrics or METRIC_ORDER)
    if not metrics:
        return {}
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
               sensor_readings.raw_value,
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
            "raw_value": row["raw_value"],
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


def get_daily_series(metric="pm25", floor_id=None, series_timezone=None):
    return _get_time_series(
        metric=metric,
        floor_id=floor_id,
        bucket="hour",
        series_timezone=series_timezone,
    )


def _coerce_series_timezone(series_timezone):
    if isinstance(series_timezone, str) and series_timezone.strip():
        timezone_name = series_timezone.strip()
        if timezone_name in SERIES_TIMEZONE_FALLBACKS:
            return SERIES_TIMEZONE_FALLBACKS[timezone_name]
        try:
            return ZoneInfo(timezone_name)
        except Exception:
            return timezone.utc
    return series_timezone or timezone.utc


def _get_latest_metric_timestamp(metric, floor_id=None):
    params = [metric]
    floor_clause = ""
    if floor_id:
        floor_clause = "AND floor_id = ?"
        params.append(floor_id)
    query = f"""
        SELECT MAX(ts) AS max_ts
        FROM sensor_readings
        WHERE metric = ? {floor_clause}
    """
    with connect(SENSOR_DB) as conn:
        row = conn.execute(query, params).fetchone()
    if not row or not row["max_ts"]:
        return None
    return datetime.fromisoformat(row["max_ts"])


def get_weekly_series(metric="pm25", floor_id=None, series_timezone=None):
    return _get_time_series(
        metric=metric,
        floor_id=floor_id,
        bucket="day",
        series_timezone=series_timezone,
    )


def _get_time_series(metric="pm25", floor_id=None, bucket="hour", series_timezone=None):
    series_timezone = _coerce_series_timezone(series_timezone)
    latest_ts = _get_latest_metric_timestamp(metric, floor_id=floor_id)
    if latest_ts is None:
        return [], []
    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.replace(tzinfo=timezone.utc)
    local_latest = latest_ts.astimezone(series_timezone)
    params = [metric]
    floor_clause = ""
    if floor_id:
        floor_clause = "AND floor_id = ?"
        params.append(floor_id)

    if bucket == "day":
        local_end = local_latest.replace(hour=0, minute=0, second=0, microsecond=0)
        local_start = local_end - timedelta(days=6)
        utc_start = local_start.astimezone(timezone.utc)
        utc_end = (local_end + timedelta(days=1)).astimezone(timezone.utc)
        query = f"""
        SELECT ts, value
        FROM sensor_readings
        WHERE metric = ? AND ts >= ? AND ts < ? {floor_clause}
        ORDER BY ts
        """
        query_params = [metric, utc_start.isoformat(), utc_end.isoformat(), *params[1:]]
        bucket_labels = [
            (local_start + timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in range(7)
        ]
        buckets = {label: [] for label in bucket_labels}
        label_format = "%Y-%m-%d"
    else:
        local_end = local_latest.replace(minute=0, second=0, microsecond=0)
        local_start = local_end - timedelta(hours=23)
        utc_start = local_start.astimezone(timezone.utc)
        utc_end = (local_end + timedelta(hours=1)).astimezone(timezone.utc)
        query = f"""
        SELECT ts, value
        FROM sensor_readings
        WHERE metric = ? AND ts >= ? AND ts < ? {floor_clause}
        ORDER BY ts
        """
        query_params = [metric, utc_start.isoformat(), utc_end.isoformat(), *params[1:]]
        bucket_labels = [
            (local_start + timedelta(hours=offset)).strftime("%H:00")
            for offset in range(24)
        ]
        buckets = {label: [] for label in bucket_labels}
        label_format = "%H:00"

    with connect(SENSOR_DB) as conn:
        rows = conn.execute(query, query_params).fetchall()

    for row in rows:
        row_ts = datetime.fromisoformat(row["ts"])
        if row_ts.tzinfo is None:
            row_ts = row_ts.replace(tzinfo=timezone.utc)
        bucket_label = row_ts.astimezone(series_timezone).strftime(label_format)
        if bucket_label in buckets and row["value"] is not None:
            buckets[bucket_label].append(float(row["value"]))

    labels = []
    values = []
    for label in bucket_labels:
        bucket_values = buckets[label]
        if not bucket_values:
            continue
        labels.append(label)
        values.append(round(sum(bucket_values) / len(bucket_values), 2))
    return labels, values


def get_sensor_time_bounds(floor_id=None, device_id=None, use_ingested_at=False):
    params = []
    clauses = []
    if floor_id:
        clauses.append("floor_id = ?")
        params.append(floor_id)
    if device_id:
        clauses.append("device_id = ?")
        params.append(device_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    time_expr = "COALESCE(ingested_at, ts)" if use_ingested_at else "ts"
    query = f"""
        SELECT MIN({time_expr}) AS min_ts, MAX({time_expr}) AS max_ts
        FROM sensor_readings
        {where_clause}
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


def clear_alarm_history():
    from services.db import connect, ALARM_DB

    with connect(ALARM_DB) as conn:
        conn.execute("DELETE FROM action_history")


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
            WHERE device_id = ? AND metric = ? AND value = ? AND ts > ? AND active = 1
            ORDER BY ts DESC
            LIMIT 1
            """,
            (alarm["device_id"], alarm["metric"], alarm["value"], alarm["ts"]),
        ).fetchone()
        should_delete = not newer_alarm

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
                datetime.now(timezone.utc).isoformat(),
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
    if should_delete:
        with connect(SENSOR_DB) as conn:
            conn.execute("DELETE FROM alarm_events WHERE id = ?", (alarm_id,))
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
