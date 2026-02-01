import csv
import io
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from services import data as data_service
from services import settings as settings_service
from services.db import SENSOR_DB, connect, init_all, seed_demo_data


app = Flask(__name__)
app.secret_key = "replace-with-secure-secret"

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

UTC_PLUS_7 = timezone(timedelta(hours=7))
UTC_PLUS_6_5 = timezone(timedelta(hours=6, minutes=30))


def parse_date_range(start_str, end_str, default_tz):
    def parse(value):
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(value)

    start_dt = parse(start_str)
    end_dt = parse(end_str)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=default_tz)
    else:
        start_dt = start_dt.astimezone(default_tz)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=default_tz)
    else:
        end_dt = end_dt.astimezone(default_tz)
    return start_dt, end_dt


def resolve_active_system(settings):
    requested = request.args.get("system")
    if requested in settings_service.SYSTEM_KEYS:
        return requested
    system_navigation = settings.get("system_navigation", {})
    for key in settings_service.SYSTEM_KEYS:
        if system_navigation.get(key):
            return key
    return settings_service.SYSTEM_KEYS[0]


def get_enabled_metric_options(settings, system_key):
    if system_key == "fire":
        options = data_service.get_fire_metric_options()
    else:
        options = data_service.get_metric_options()
    visibility = settings.get("tag_visibility", {}).get(system_key, {})
    if isinstance(visibility, dict) and visibility:
        filtered = [option for option in options if visibility.get(option["key"], False)]
        if filtered:
            return filtered
    return options


def derive_device_severity(devices, device_metric_severity, alarm_severity, settings):
    levels = settings.get("severity_levels", [])
    severity_rank = {level["label"]: index for index, level in enumerate(levels)}
    fire_levels = settings.get("fire_severity_mapping", [])
    fire_rank_offset = len(severity_rank)
    for index, level in enumerate(fire_levels):
        label = (level.get("label") or "").strip()
        if not label or label in severity_rank:
            continue
        severity_rank[label] = fire_rank_offset + index

    def get_rank(label):
        if not label:
            return -1
        return severity_rank.get(label, -1)

    device_severity = {}
    for device in devices:
        device_id = device["device_id"]
        metric_levels = device_metric_severity.get(device_id, {})
        best_label = ""
        best_rank = -1
        for level in metric_levels.values():
            label = level.get("label") if level else ""
            rank = get_rank(label)
            if rank > best_rank:
                best_rank = rank
                best_label = label
        alarm_label = alarm_severity.get(device_id, "")
        if get_rank(alarm_label) > best_rank:
            best_label = alarm_label
        device_severity[device_id] = best_label
    return device_severity


@app.before_request
def ensure_init():
    init_all()
    seed_demo_data()


@app.context_processor
def inject_globals():
    settings = settings_service.load_settings()
    active_alarms = data_service.get_active_alarms()
    critical_levels = settings.get("critical_levels", [])
    return {
        "settings": settings,
        "is_admin": session.get("is_admin", False),
        "alarm_count": data_service.get_alarm_count(),
        "calendar_value": data_service.get_calendar_value(),
        "avg_signal": data_service.get_avg_signal_quality(),
        "has_critical": any(alarm["severity"] in critical_levels for alarm in active_alarms),
        "current_system": resolve_active_system(settings),
    }


@app.route("/")
def index():
    settings = settings_service.load_settings()
    active_system = resolve_active_system(settings)
    floors = data_service.get_floor_list()
    floor_id = request.args.get("floor") or (floors[0] if floors else None)
    devices = data_service.get_devices()
    alarm_severity = data_service.get_device_alarm_severity()
    active_alarms = data_service.get_active_alarms()

    def device_value(device, key, default=None):
        if hasattr(device, "get"):
            return device.get(key, default)
        try:
            return device[key]
        except (KeyError, TypeError):
            return default

    device_label_map = {}
    for device in devices:
        device_id = device_value(device, "device_id")
        if device_id:
            device_label_map[device_id] = device_value(device, "label")
    metric_options = get_enabled_metric_options(settings, active_system)
    metric_option_map = {
        option["key"]: {"label": option["label"], "unit": option["unit"]}
        for option in metric_options
    }
    metric_keys = [option["key"] for option in metric_options]
    fallback_metric = metric_keys[0] if metric_keys else "pm25"
    daily_metric = request.args.get("daily_metric") or fallback_metric
    weekly_metric = request.args.get("weekly_metric") or fallback_metric
    if daily_metric not in metric_keys:
        daily_metric = fallback_metric
    if weekly_metric not in metric_keys:
        weekly_metric = fallback_metric

    daily_labels, daily_values = data_service.get_daily_series(daily_metric, floor_id=floor_id)
    weekly_labels, weekly_values = data_service.get_weekly_series(weekly_metric, floor_id=floor_id)

    sensor_cards = data_service.get_latest_avg_metrics(floor_id=floor_id)
    sensor_card_severity = {
        metric: data_service.get_metric_severity(settings, metric, data.get("value"))
        for metric, data in sensor_cards.items()
    }
    indoor_outdoor = data_service.get_latest_indoor_outdoor(floor_id=floor_id)
    indoor_outdoor_aqi = data_service.get_indoor_outdoor_aqi(floor_id=floor_id)
    device_metrics = data_service.get_latest_device_metrics(floor_id=floor_id)
    device_metric_severity = {
        device_id: {
            metric: data_service.get_metric_severity(settings, metric, reading.get("value"))
            for metric, reading in metrics.items()
        }
        for device_id, metrics in device_metrics.items()
    }
    device_severity = derive_device_severity(
        devices, device_metric_severity, alarm_severity, settings
    )
    critical_levels = set(settings.get("critical_levels", []))
    if metric_keys:
        active_alarms = [alarm for alarm in active_alarms if alarm["metric"] in metric_keys]

    def format_alarm_time(timestamp):
        if not timestamp:
            return ""
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError:
            return timestamp
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        local_ts = parsed.astimezone(UTC_PLUS_7)
        return local_ts.strftime("%d/%m/%Y %I:%M %p")

    active_alarms = [
        {**dict(alarm), "display_time": format_alarm_time(alarm["ts"])}
        for alarm in active_alarms
    ]

    def is_outdoor_zone(zone):
        if not zone:
            return False
        zone_value = zone.lower()
        return "outdoor" in zone_value or "outside" in zone_value

    indoor_critical_count = 0
    outdoor_critical_count = 0
    for device in devices:
        device_id = device_value(device, "device_id")
        severity = device_severity.get(device_id)
        if severity not in critical_levels:
            continue
        if is_outdoor_zone(device_value(device, "zone", "")):
            outdoor_critical_count += 1
        else:
            indoor_critical_count += 1

    default_view_device = devices[0]["device_id"] if devices else None
    daily_view_end = datetime.now()
    daily_view_start = daily_view_end - timedelta(hours=24)
    weekly_view_end = datetime.now()
    weekly_view_start = weekly_view_end - timedelta(days=7)
    all_data_start, all_data_end = data_service.get_sensor_time_bounds(floor_id=floor_id)
    if not all_data_start or not all_data_end:
        all_data_start, all_data_end = daily_view_start, daily_view_end
    default_view_interval = 10

    return render_template(
        "index.html",
        active_system=active_system,
        floors=floors,
        active_floor=floor_id,
        devices=devices,
        alarm_severity=alarm_severity,
        active_alarms=active_alarms,
        device_label_map=device_label_map,
        daily_labels=daily_labels,
        daily_values=daily_values,
        weekly_labels=weekly_labels,
        weekly_values=weekly_values,
        daily_metric=daily_metric,
        weekly_metric=weekly_metric,
        sensor_cards=sensor_cards,
        sensor_card_severity=sensor_card_severity,
        indoor_outdoor=indoor_outdoor,
        indoor_outdoor_aqi=indoor_outdoor_aqi,
        device_metrics=device_metrics,
        metric_options=metric_options,
        metric_option_map=metric_option_map,
        device_metric_severity=device_metric_severity,
        device_severity=device_severity,
        indoor_critical_count=indoor_critical_count,
        outdoor_critical_count=outdoor_critical_count,
        now=datetime.now(),
        default_view_device=default_view_device,
        daily_view_start=daily_view_start.strftime("%Y-%m-%dT%H:%M"),
        daily_view_end=daily_view_end.strftime("%Y-%m-%dT%H:%M"),
        weekly_view_start=weekly_view_start.strftime("%Y-%m-%dT%H:%M"),
        weekly_view_end=weekly_view_end.strftime("%Y-%m-%dT%H:%M"),
        all_data_start=all_data_start.strftime("%Y-%m-%dT%H:%M"),
        all_data_end=all_data_end.strftime("%Y-%m-%dT%H:%M"),
        default_view_interval=default_view_interval,
        status_label=data_service.aggregate_status_label(settings),
    )


@app.route("/map")
def map_full():
    settings = settings_service.load_settings()
    active_system = resolve_active_system(settings)
    floors = data_service.get_floor_list()
    floor_id = request.args.get("floor") or (floors[0] if floors else None)
    devices = data_service.get_devices()
    alarm_severity = data_service.get_device_alarm_severity()
    metric_options = get_enabled_metric_options(settings, active_system)
    device_metrics = data_service.get_latest_device_metrics(floor_id=floor_id)
    device_metric_severity = {
        device_id: {
            metric: data_service.get_metric_severity(settings, metric, reading.get("value"))
            for metric, reading in metrics.items()
        }
        for device_id, metrics in device_metrics.items()
    }
    device_severity = derive_device_severity(
        devices, device_metric_severity, alarm_severity, settings
    )
    return render_template(
        "map_full.html",
        floors=floors,
        active_floor=floor_id,
        devices=devices,
        alarm_severity=alarm_severity,
        metric_options=metric_options,
        device_metrics=device_metrics,
        device_metric_severity=device_metric_severity,
        device_severity=device_severity,
    )


@app.route("/export/sensor.csv")
def export_sensor_csv():
    settings = settings_service.load_settings()
    active_system = resolve_active_system(settings)
    metric_options = get_enabled_metric_options(settings, active_system)
    allowed_metrics = {option["key"] for option in metric_options}
    rows = data_service.get_sensor_readings_csv()
    csv_path = os.path.join(BASE_DIR, "sensor_export.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts", "device_id", "floor_id", "metric", "value", "unit"])
        for row in rows:
            if allowed_metrics and row["metric"] not in allowed_metrics:
                continue
            writer.writerow([row["ts"], row["device_id"], row["floor_id"], row["metric"], row["value"], row["unit"]])
    return send_file(csv_path, as_attachment=True, download_name="sensor_readings.csv")


@app.route("/settings/export.csv")
def export_settings_csv():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    settings = settings_service.load_settings()
    devices = data_service.get_devices()
    floor_plan_sensors = {}
    for device in devices:
        floor_id = device["floor_id"] or ""
        floor_plan_sensors.setdefault(floor_id, []).append(
            {
                "device_id": device["device_id"],
                "location_x": device["location_x"],
                "location_y": device["location_y"],
            }
        )
    export_settings = dict(settings)
    export_settings["floor_plan_sensors"] = floor_plan_sensors
    csv_path = os.path.join(BASE_DIR, "settings_export.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["key", "value"])
        for key, value in export_settings.items():
            writer.writerow([key, json.dumps(value)])
    return send_file(csv_path, as_attachment=True, download_name="settings.csv")


@app.route("/view_data")
def view_data():
    settings = settings_service.load_settings()
    active_system = resolve_active_system(settings)
    device = request.args.get("device")
    start = request.args.get("start")
    end = request.args.get("end")
    interval_minutes = request.args.get("interval", type=int) or 10

    if not device or not start or not end:
        return "Missing required parameters", 400

    try:
        start_dt, end_dt = parse_date_range(start, end, UTC_PLUS_7)
    except ValueError:
        return "Invalid date format", 400

    if end_dt < start_dt:
        return "Invalid date format", 400

    start_utc = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_dt.astimezone(timezone.utc).replace(tzinfo=None)

    query = """
        SELECT ts, device_id, metric, value, unit, topic
        FROM sensor_readings
        WHERE device_id = ? AND ts BETWEEN ? AND ?
        ORDER BY ts ASC
    """
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(query, (device, start_utc.isoformat(), end_utc.isoformat())).fetchall()

    local_tz = UTC_PLUS_6_5 if device == "Room Environment #4" else UTC_PLUS_7
    aggregates = {}
    for row in rows:
        value = row["value"]
        if value is None or value == "" or str(value).strip().upper() == "N/A":
            continue
        ts = datetime.fromisoformat(row["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        local_ts = ts.astimezone(local_tz).replace(tzinfo=None)
        bucket = local_ts.replace(
            minute=(local_ts.minute // interval_minutes) * interval_minutes,
            second=0,
            microsecond=0,
        )
        topic = (row["topic"] or "Live").strip() or "Live"
        key = (bucket, topic, row["metric"])
        if key not in aggregates:
            aggregates[key] = {"sum": 0.0, "count": 0, "unit": row["unit"]}
        aggregates[key]["sum"] += float(value)
        aggregates[key]["count"] += 1

    metric_options = get_enabled_metric_options(settings, active_system)
    metric_order = [option["key"] for option in metric_options]
    records = []
    bucket_topics = sorted({(bucket, topic) for bucket, topic, _metric in aggregates.keys()})
    for bucket, topic in bucket_topics:
        record = {
            "timestamp": bucket.strftime("%d/%m/%Y %I:%M %p"),
            "gateway": "N/A",
            "topic": topic,
            "device": device,
            "metrics": {},
        }
        for metric in metric_order:
            stats = aggregates.get((bucket, topic, metric))
            if stats:
                avg_value = stats["sum"] / stats["count"]
                record["metrics"][metric] = round(avg_value, 2)
            else:
                record["metrics"][metric] = None
        records.append(record)

    start_display = start_dt.strftime("%Y-%m-%dT%H:%M")
    end_display = end_dt.strftime("%Y-%m-%dT%H:%M")
    start_date = start_dt.date().isoformat()
    end_date = end_dt.date().isoformat()
    devices = data_service.get_devices()

    return render_template(
        "view_data.html",
        data=records,
        start_datetime=start_display,
        end_datetime=end_display,
        start_date=start_date,
        end_date=end_date,
        active_device=device,
        interval_minutes=interval_minutes,
        devices=devices,
        metric_options=metric_options,
    )


@app.post("/view_data/delete")
def delete_view_data():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    device = request.form.get("device")
    start = request.form.get("start")
    end = request.form.get("end")
    if not device or not start or not end:
        return redirect(url_for("view_data", device=device, start=start, end=end, interval=10))

    try:
        start_dt, end_dt = parse_date_range(start, end, UTC_PLUS_7)
    except ValueError:
        return redirect(url_for("view_data", device=device, start=start, end=end, interval=10))

    if end_dt < start_dt:
        return redirect(url_for("view_data", device=device, start=start, end=end, interval=10))

    start_utc = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_dt.astimezone(timezone.utc).replace(tzinfo=None)
    with connect(SENSOR_DB) as conn:
        conn.execute(
            "DELETE FROM sensor_readings WHERE device_id = ? AND ts BETWEEN ? AND ?",
            (device, start_utc.isoformat(), end_utc.isoformat()),
        )
        conn.execute(
            "DELETE FROM alarm_events WHERE device_id = ? AND ts BETWEEN ? AND ?",
            (device, start_utc.isoformat(), end_utc.isoformat()),
        )
    return redirect(
        url_for(
            "view_data",
            device=device,
            start=start,
            end=end,
            interval=request.form.get("interval", type=int) or 10,
        )
    )


@app.post("/view_data/test/seed")
def seed_test_data():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    device = request.form.get("device")
    if not start_date or not end_date:
        return redirect(
            url_for(
                "view_data",
                device=device,
                start=request.form.get("start"),
                end=request.form.get("end"),
                interval=request.form.get("interval", type=int) or 10,
            )
        )

    devices = data_service.get_devices()
    device_ids = [row["device_id"] for row in devices]
    if not device_ids:
        return redirect(
            url_for(
                "view_data",
                device=device,
                start=request.form.get("start"),
                end=request.form.get("end"),
                interval=request.form.get("interval", type=int) or 10,
            )
        )

    script_path = os.path.join(BASE_DIR, "scripts", "seed_date_range.py")
    command = [
        sys.executable,
        script_path,
        "--start",
        start_date,
        "--end",
        end_date,
        "--topic",
        "Test",
    ]
    for device_id in device_ids:
        command.extend(["--device", device_id])
    subprocess.run(
        command,
        check=True,
    )
    return redirect(
        url_for(
            "view_data",
            device=request.form.get("device"),
            start=request.form.get("start"),
            end=request.form.get("end"),
            interval=request.form.get("interval", type=int) or 10,
        )
    )


@app.post("/view_data/test/delete")
def delete_test_data():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    params = ["Test"]
    date_clause = ""
    if start_date and end_date:
        date_clause = "AND date(ts) BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    with connect(SENSOR_DB) as conn:
        conn.execute(
            f"DELETE FROM sensor_readings WHERE topic = ? {date_clause}",
            params,
        )
    return redirect(
        url_for(
            "view_data",
            device=request.form.get("device"),
            start=request.form.get("start"),
            end=request.form.get("end"),
            interval=request.form.get("interval", type=int) or 10,
        )
    )


@app.post("/settings/import")
def import_settings_csv():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    settings_file = request.files.get("settings_csv")
    if not settings_file or not settings_file.filename:
        return redirect(url_for("settings"))

    settings = settings_service.load_settings()
    file_content = settings_file.stream.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(file_content))
    for row in reader:
        key = (row.get("key") or "").strip()
        value = row.get("value")
        if not key:
            continue
        if key == "floor_plan_sensors":
            try:
                layout_payload = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(layout_payload, dict):
                for floor_id, sensors in layout_payload.items():
                    if not isinstance(sensors, list):
                        continue
                    for sensor in sensors:
                        if not isinstance(sensor, dict):
                            continue
                        device_id = (sensor.get("device_id") or "").strip()
                        if not device_id:
                            continue
                        try:
                            location_x = float(sensor.get("location_x"))
                            location_y = float(sensor.get("location_y"))
                        except (TypeError, ValueError):
                            continue
                        location_x = max(0, min(100, location_x))
                        location_y = max(0, min(100, location_y))
                        data_service.update_device_layout(
                            device_id, floor_id, location_x, location_y
                        )
            continue
        try:
            settings[key] = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            settings[key] = value
    settings_service.save_settings(settings)
    return redirect(url_for("settings"))


@app.route("/graphs/daily")
def graphs_daily():
    metric = request.args.get("metric", "pm25")
    floor_id = request.args.get("floor")
    labels, values = data_service.get_daily_series(metric, floor_id)
    return jsonify({"labels": labels, "values": values})


@app.route("/graphs/weekly")
def graphs_weekly():
    metric = request.args.get("metric", "pm25")
    floor_id = request.args.get("floor")
    labels, values = data_service.get_weekly_series(metric, floor_id)
    return jsonify({"labels": labels, "values": values})


@app.route("/alarms")
def alarms():
    settings = settings_service.load_settings()
    active_system = resolve_active_system(settings)
    metric_options = get_enabled_metric_options(settings, active_system)
    metric_keys = {option["key"] for option in metric_options}
    alarms_view = request.args.get("view") or "today"
    if session.get("is_admin") and alarms_view == "today":
        active_alarms = data_service.get_today_alarms()
    else:
        active_alarms = data_service.get_active_alarms()
    history = data_service.get_alarm_history()
    if metric_keys:
        active_alarms = [alarm for alarm in active_alarms if alarm["metric"] in metric_keys]
        history = [alarm for alarm in history if alarm["metric"] in metric_keys]
    today = datetime.now(timezone.utc).date().isoformat()
    action_start = request.args.get("action_start") or today
    action_end = request.args.get("action_end") or today
    devices = data_service.get_devices()

    def device_value(device, key):
        if hasattr(device, "get"):
            return device.get(key)
        try:
            return device[key]
        except (KeyError, TypeError):
            return None

    device_label_map = {}
    device_floors = set()
    for device in devices:
        device_id = device_value(device, "device_id")
        if device_id:
            device_label_map[device_id] = device_value(device, "label")
        floor_id = device_value(device, "floor_id")
        if floor_id:
            device_floors.add(floor_id)
    floor_plan_ids = set(settings.get("floor_plans", {}).keys())
    floor_name_ids = set(settings.get("floor_names", {}).keys())
    floors = sorted(floor_plan_ids | device_floors | floor_name_ids)
    return render_template(
        "alarms.html",
        active_alarms=active_alarms,
        history=history,
        action_start=action_start,
        action_end=action_end,
        alarms_view=alarms_view,
        devices=devices,
        device_label_map=device_label_map,
        floors=floors,
        alarm_metric_options=metric_options,
    )


@app.post("/alarms/response")
def save_alarm_response():
    alarm_id = request.form.get("alarm_id", type=int)
    action_owner = request.form.get("action_owner", "").strip() or None
    action_note = request.form.get("action_note", "").strip() or None
    checklist = request.form.getlist("checklist")
    checklist_value = ",".join(checklist) if checklist else None
    if alarm_id:
        data_service.save_alarm_response(
            alarm_id,
            action_owner=action_owner,
            action_note=action_note,
            checklist=checklist_value,
        )
    return redirect(url_for("alarms"))


@app.post("/alarms/history/clear")
def clear_alarm_history():
    if not session.get("is_admin"):
        return redirect(url_for("login"))
    data_service.clear_alarm_history()
    return redirect(url_for("alarms"))


@app.route("/alarms/actions.csv")
def export_action_history():
    today = datetime.now(timezone.utc).date().isoformat()
    action_start = request.args.get("action_start") or today
    action_end = request.args.get("action_end") or today
    rows = data_service.get_action_history(action_start, action_end)
    csv_path = os.path.join(BASE_DIR, "action_history_export.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "action_ts",
                "alarm_ts",
                "device_id",
                "floor_id",
                "metric",
                "value",
                "severity",
                "message",
                "action_owner",
                "action_note",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["action_ts"],
                    row["alarm_ts"],
                    row["device_id"],
                    row["floor_id"],
                    row["metric"],
                    row["value"],
                    row["severity"],
                    row["message"],
                    row["action_owner"],
                    row["action_note"],
                ]
            )
    return send_file(csv_path, as_attachment=True, download_name="action_history.csv")


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    settings = settings_service.load_settings()
    devices = data_service.get_devices()
    device_floors = {device["floor_id"] for device in devices if device["floor_id"]}
    floor_plan_ids = set(settings.get("floor_plans", {}).keys())
    floors = sorted(floor_plan_ids | device_floors)
    available_uploads = []
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(path):
                available_uploads.append(f"static/uploads/{filename}")
    available_uploads.sort()
    system_navigation = settings.get("system_navigation", {})
    default_system = next(
        (key for key in settings_service.SYSTEM_KEYS if system_navigation.get(key)),
        settings_service.SYSTEM_KEYS[0],
    )
    if request.method == "POST":
        settings["project_name"] = request.form.get("project_name", settings["project_name"])
        settings["location_label"] = request.form.get("location_label", settings["location_label"])
        settings["floor_auto_rotate_seconds"] = int(
            request.form.get("floor_auto_rotate_seconds", settings["floor_auto_rotate_seconds"])
        )
        settings["sensor_icon_size"] = int(
            request.form.get("sensor_icon_size", settings["sensor_icon_size"])
        )
        settings["logo_icon_size"] = int(
            request.form.get("logo_icon_size", settings["logo_icon_size"])
        )
        settings["show_icons"] = {
            "bell": bool(request.form.get("show_bell")),
            "calendar": bool(request.form.get("show_calendar")),
            "download": bool(request.form.get("show_download")),
            "settings": True,
        }
        settings["show_severity_lines"] = bool(request.form.get("show_severity_lines"))
        settings["system_navigation"] = {
            "iaq": bool(request.form.get("nav_system_iaq")),
            "energy": bool(request.form.get("nav_system_energy")),
            "waste": bool(request.form.get("nav_system_waste")),
            "fire": bool(request.form.get("nav_system_fire")),
        }
        tag_visibility = settings.get("tag_visibility", {})
        tag_visibility["iaq"] = {
            "temperature": bool(request.form.get("iaq_tag_temperature")),
            "pm25": bool(request.form.get("iaq_tag_pm25")),
            "pm10": bool(request.form.get("iaq_tag_pm10")),
            "humidity": bool(request.form.get("iaq_tag_humidity")),
            "tvoc": bool(request.form.get("iaq_tag_tvoc")),
            "co2": bool(request.form.get("iaq_tag_co2")),
        }
        tag_visibility["fire"] = {
            "smoke": bool(request.form.get("fire_tag_smoke")),
            "heat": bool(request.form.get("fire_tag_heat")),
            "flow_switch": bool(request.form.get("fire_tag_flow_switch")),
            "supervisory_valve": bool(request.form.get("fire_tag_supervisory_valve")),
            "manual": bool(request.form.get("fire_tag_manual")),
            "gas": bool(request.form.get("fire_tag_gas")),
        }
        settings["tag_visibility"] = tag_visibility
        card_header_color = request.form.get("card_header_color", settings["card_header_color"])
        card_body_color = request.form.get("card_body_color", settings["card_body_color"])
        page_background_color = request.form.get(
            "page_background_color", settings["page_background_color"]
        )
        settings["card_header_color"] = (
            "transparent" if request.form.get("card_header_transparent") else card_header_color
        )
        settings["card_body_color"] = (
            "transparent" if request.form.get("card_body_transparent") else card_body_color
        )
        settings["page_background_color"] = (
            "transparent"
            if request.form.get("page_background_transparent")
            else page_background_color
        )

        modules = settings.get("modules", {})
        existing_top_definition = modules.get("top_definition", {})
        updated_top_definition = {}
        for system_key in settings_service.SYSTEM_KEYS:
            system_defaults = existing_top_definition.get(system_key, {})
            default_columns = system_defaults.get("columns", {})
            labels = request.form.getlist(f"top_definition_legend_label_{system_key}")
            colors = request.form.getlist(f"top_definition_legend_color_{system_key}")
            legend = []
            for label, color in zip(labels, colors):
                if label.strip() or color.strip():
                    legend.append(
                        {"label": label.strip(), "color": color.strip() or "#28a745"}
                    )
            top_definition_mode = request.form.get(
                f"top_definition_mode_{system_key}",
                system_defaults.get("mode", "average"),
            )
            if top_definition_mode not in ("average", "critical"):
                top_definition_mode = "average"
            updated_top_definition[system_key] = {
                "enabled": bool(request.form.get(f"top_definition_enabled_{system_key}")),
                "title": request.form.get(
                    f"top_definition_title_{system_key}",
                    system_defaults.get("title", "Top Definition"),
                ).strip()
                or "Top Definition",
                "header": request.form.get(
                    f"top_definition_header_{system_key}",
                    system_defaults.get("header", "Average Indoor/Outdoor IAQ"),
                ).strip()
                or system_defaults.get("header", "Average Indoor/Outdoor IAQ"),
                "columns": {
                    "indoor": request.form.get(
                        f"top_definition_column_indoor_{system_key}",
                        default_columns.get("indoor", "Indoor"),
                    ).strip()
                    or default_columns.get("indoor", "Indoor"),
                    "outdoor": request.form.get(
                        f"top_definition_column_outdoor_{system_key}",
                        default_columns.get("outdoor", "Outdoor"),
                    ).strip()
                    or default_columns.get("outdoor", "Outdoor"),
                    "indoor_enabled": bool(
                        request.form.get(
                            f"top_definition_column_indoor_enabled_{system_key}"
                        )
                    ),
                    "outdoor_enabled": bool(
                        request.form.get(
                            f"top_definition_column_outdoor_enabled_{system_key}"
                        )
                    ),
                },
                "mode": top_definition_mode,
                "legend": legend,
            }
        modules["top_definition"] = updated_top_definition

        updated_dashboard_cards = {}
        for system_key in settings_service.SYSTEM_KEYS:
            updated_dashboard_cards[system_key] = {
                "daily_graph": bool(
                    request.form.get(f"dashboard_card_daily_graph_{system_key}")
                ),
                "weekly_overview": bool(
                    request.form.get(f"dashboard_card_weekly_overview_{system_key}")
                ),
                "sensor_average": bool(
                    request.form.get(f"dashboard_card_sensor_average_{system_key}")
                ),
                "alerts_notifications": bool(
                    request.form.get(f"dashboard_card_alerts_notifications_{system_key}")
                ),
            }
        modules["dashboard_cards"] = updated_dashboard_cards
        settings["modules"] = modules

        fire_severity_labels = request.form.getlist("fire_severity_label")
        fire_severity_colors = request.form.getlist("fire_severity_color")
        fire_severity_text_colors = request.form.getlist("fire_severity_text_color")
        fire_severity_icons = request.form.getlist("fire_severity_icon")
        fire_smoke_values = request.form.getlist("fire_smoke")
        fire_heat_values = request.form.getlist("fire_heat")
        fire_flow_switch_values = request.form.getlist("fire_flow_switch")
        fire_supervisory_values = request.form.getlist("fire_supervisory_valve")
        fire_manual_values = request.form.getlist("fire_manual")
        fire_gas_values = request.form.getlist("fire_gas")
        fire_severity_mapping = []
        for (
            label,
            color,
            text_color,
            icon,
            smoke,
            heat,
            flow_switch,
            supervisory_valve,
            manual,
            gas,
        ) in zip(
            fire_severity_labels,
            fire_severity_colors,
            fire_severity_text_colors,
            fire_severity_icons,
            fire_smoke_values,
            fire_heat_values,
            fire_flow_switch_values,
            fire_supervisory_values,
            fire_manual_values,
            fire_gas_values,
        ):
            if (
                label.strip()
                or color.strip()
                or text_color.strip()
                or icon.strip()
                or smoke.strip()
                or heat.strip()
                or flow_switch.strip()
                or supervisory_valve.strip()
                or manual.strip()
                or gas.strip()
            ):
                fire_severity_mapping.append(
                    {
                        "label": label.strip(),
                        "color": color.strip(),
                        "text_color": text_color.strip(),
                        "icon": icon.strip(),
                        "smoke": smoke.strip(),
                        "heat": heat.strip(),
                        "flow_switch": flow_switch.strip(),
                        "supervisory_valve": supervisory_valve.strip(),
                        "manual": manual.strip(),
                        "gas": gas.strip(),
                    }
                )
        settings["fire_severity_mapping"] = fire_severity_mapping

        severity_labels = request.form.getlist("severity_label")
        severity_colors = request.form.getlist("severity_color")
        severity_icons = request.form.getlist("severity_icon")
        severity_temperatures = request.form.getlist("severity_temperature")
        severity_humidity = request.form.getlist("severity_humidity")
        severity_pm25 = request.form.getlist("severity_pm25")
        severity_pm10 = request.form.getlist("severity_pm10")
        severity_tvoc = request.form.getlist("severity_tvoc")
        severity_co2 = request.form.getlist("severity_co2")
        severity_levels = []

        def parse_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        for label, color, icon, temperature, humidity, pm25, pm10, tvoc, co2 in zip(
            severity_labels,
            severity_colors,
            severity_icons,
            severity_temperatures,
            severity_humidity,
            severity_pm25,
            severity_pm10,
            severity_tvoc,
            severity_co2,
        ):
            if label.strip():
                severity_levels.append(
                    {
                        "label": label.strip(),
                        "color": color,
                        "icon": icon,
                        "thresholds": {
                            "temperature": parse_float(temperature),
                            "humidity": parse_float(humidity),
                            "pm25": parse_float(pm25),
                            "pm10": parse_float(pm10),
                            "tvoc": parse_float(tvoc),
                            "co2": parse_float(co2),
                        },
                    }
                )
        settings["severity_levels"] = severity_levels
        settings["critical_levels"] = request.form.getlist("critical_levels")

        old_floor_logo_icon = settings.get("floor_logo_icon", "")

        if "sensor_icon" in request.files:
            file = request.files["sensor_icon"]
            if file and file.filename:
                filename = secure_filename(file.filename)
                path = os.path.join(UPLOAD_DIR, filename)
                file.save(path)
                settings["sensor_icon"] = f"static/uploads/{filename}"
        sensor_icon_existing = request.form.get("sensor_icon_existing", "").strip()
        if sensor_icon_existing:
            settings["sensor_icon"] = sensor_icon_existing

        if "floor_logo_icon" in request.files:
            file = request.files["floor_logo_icon"]
            if file and file.filename:
                filename = secure_filename(file.filename)
                path = os.path.join(UPLOAD_DIR, filename)
                file.save(path)
                settings["floor_logo_icon"] = f"static/uploads/{filename}"
        floor_logo_icon_existing = request.form.get("floor_logo_icon_existing", "").strip()
        if floor_logo_icon_existing or floor_logo_icon_existing == "":
            settings["floor_logo_icon"] = floor_logo_icon_existing

        if "project_logo" in request.files:
            file = request.files["project_logo"]
            if file and file.filename:
                filename = secure_filename(file.filename)
                path = os.path.join(UPLOAD_DIR, filename)
                file.save(path)
                settings["project_logo"] = f"static/uploads/{filename}"
        project_logo_existing = request.form.get("project_logo_existing", "").strip()
        if project_logo_existing or project_logo_existing == "":
            settings["project_logo"] = project_logo_existing

        new_floor_logo_icon = settings.get("floor_logo_icon", "")
        if new_floor_logo_icon != old_floor_logo_icon:
            floor_logos = settings.get("floor_plan_logos", {})
            for floor_id, logos in floor_logos.items():
                for logo in logos:
                    if logo.get("logo_icon") == old_floor_logo_icon:
                        if new_floor_logo_icon:
                            logo["logo_icon"] = new_floor_logo_icon
                        else:
                            logo.pop("logo_icon", None)
                    logo["floor_id"] = floor_id
            settings["floor_plan_logos"] = floor_logos

        existing_floor_plans = settings.get("floor_plans", {}).copy()
        floor_ids = request.form.getlist("floor_id")
        floor_names = request.form.getlist("floor_name")
        floor_files = request.files.getlist("floor_plan")
        floor_existing = request.form.getlist("floor_plan_existing")
        updated_floor_plans = {}
        updated_floor_names = {}
        for index, floor_id in enumerate(floor_ids):
            floor_id = floor_id.strip()
            if not floor_id:
                continue
            floor_name = floor_names[index].strip() if index < len(floor_names) else ""
            if floor_name:
                updated_floor_names[floor_id] = floor_name
            floor_file = floor_files[index] if index < len(floor_files) else None
            existing_path = floor_existing[index] if index < len(floor_existing) else ""
            if floor_file and floor_file.filename:
                filename = secure_filename(floor_file.filename)
                path = os.path.join(UPLOAD_DIR, filename)
                floor_file.save(path)
                updated_floor_plans[floor_id] = f"static/uploads/{filename}"
            elif existing_path:
                updated_floor_plans[floor_id] = existing_path
            elif floor_id in settings.get("floor_plans", {}):
                updated_floor_plans[floor_id] = settings["floor_plans"][floor_id]

        settings["floor_plans"] = updated_floor_plans
        if updated_floor_names or "floor_names" in settings:
            settings["floor_names"] = updated_floor_names
        removed_floor_ids = set(existing_floor_plans.keys()) - set(updated_floor_plans.keys())
        if removed_floor_ids:
            floor_logos = settings.get("floor_plan_logos", {})
            floor_names = settings.get("floor_names", {})
            for floor_id in removed_floor_ids:
                floor_logos.pop(floor_id, None)
                floor_names.pop(floor_id, None)
                data_service.delete_devices_by_floor(floor_id)
            settings["floor_plan_logos"] = floor_logos
            settings["floor_names"] = floor_names

        settings_service.save_settings(settings)
        return redirect(url_for("settings"))

    return render_template(
        "settings.html",
        settings=settings,
        available_uploads=available_uploads,
        floors=floors,
        devices=[dict(device) for device in devices],
        default_system=default_system,
    )


@app.post("/settings/uploads")
def upload_settings_file():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "Missing file"}), 400
    filename = secure_filename(file.filename)
    if not filename:
        return jsonify({"error": "Invalid filename"}), 400
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, filename)
    file.save(path)
    upload_path = f"static/uploads/{filename}"
    return jsonify({"path": upload_path, "filename": filename})


@app.delete("/settings/uploads")
def delete_settings_file():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(silent=True) or {}
    upload_path = (payload.get("path") or "").strip()
    if not upload_path.startswith("static/uploads/"):
        return jsonify({"error": "Invalid path"}), 400
    filename = os.path.basename(upload_path)
    if not filename:
        return jsonify({"error": "Invalid filename"}), 400
    path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
    settings = settings_service.load_settings()
    updated = False
    if settings.get("floor_logo_icon") == upload_path:
        settings["floor_logo_icon"] = ""
        updated = True
    if settings.get("project_logo") == upload_path:
        settings["project_logo"] = ""
        updated = True
    if updated:
        settings_service.save_settings(settings)
    return jsonify({"deleted": upload_path, "settings_updated": updated})


@app.post("/api/devices")
def create_device():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(silent=True) or {}
    floor_id = (payload.get("floor_id") or "").strip()
    sensor_name = (payload.get("sensor_name") or "").strip() or None
    zone = (payload.get("zone") or "").strip() or None
    sensor_type = (payload.get("sensor_type") or "").strip() or None
    if not floor_id:
        return jsonify({"error": "Missing floor_id"}), 400
    device = data_service.create_device(
        floor_id,
        zone=zone or "Z1",
        sensor_type=sensor_type or "DZ",
        sensor_name=sensor_name,
    )
    return jsonify(device)


@app.post("/api/devices/<device_id>/position")
def update_device_position(device_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(silent=True) or {}
    try:
        location_x = float(payload.get("location_x"))
        location_y = float(payload.get("location_y"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid coordinates"}), 400
    location_x = max(0, min(100, location_x))
    location_y = max(0, min(100, location_y))
    data_service.update_device_position(device_id, location_x, location_y)
    return jsonify({"device_id": device_id, "location_x": location_x, "location_y": location_y})


@app.post("/api/devices/<device_id>/zone")
def update_device_zone(device_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(silent=True) or {}
    zone = (payload.get("zone") or "").strip()
    data_service.update_device_zone(device_id, zone)
    return jsonify({"device_id": device_id, "zone": zone})


@app.post("/api/devices/<device_id>/label")
def update_device_label(device_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(silent=True) or {}
    label = (payload.get("label") or "").strip()
    data_service.update_device_label(device_id, label)
    return jsonify({"device_id": device_id, "label": label})


@app.delete("/api/devices/<device_id>")
def delete_device(device_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    data_service.delete_device(device_id)
    return jsonify({"device_id": device_id})


@app.delete("/api/floors/<floor_id>/devices")
def delete_floor_devices(floor_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    data_service.delete_devices_by_floor(floor_id)
    return jsonify({"floor_id": floor_id})


@app.delete("/api/floor-plans/<floor_id>")
def delete_floor_plan(floor_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    settings = settings_service.load_settings()
    floor_plans = settings.get("floor_plans", {})
    removed = floor_plans.pop(floor_id, None)
    settings["floor_plans"] = floor_plans
    floor_logos = settings.get("floor_plan_logos", {})
    floor_logos.pop(floor_id, None)
    settings["floor_plan_logos"] = floor_logos
    floor_names = settings.get("floor_names", {})
    floor_names.pop(floor_id, None)
    settings["floor_names"] = floor_names
    if removed:
        data_service.delete_devices_by_floor(floor_id)
    settings_service.save_settings(settings)
    return jsonify({"floor_id": floor_id, "removed": bool(removed)})


@app.post("/api/floor-logos")
def create_floor_logo():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(silent=True) or {}
    floor_id = (payload.get("floor_id") or "").strip()
    label = (payload.get("label") or "").strip()
    if not floor_id:
        return jsonify({"error": "Missing floor_id"}), 400
    logo_icon = (payload.get("logo_icon") or "").strip()
    settings = settings_service.load_settings()
    if not logo_icon:
        logo_icon = settings.get("floor_logo_icon", "")
    floor_logos = settings.get("floor_plan_logos", {})
    logo_id = uuid.uuid4().hex
    new_logo = {
        "logo_id": logo_id,
        "floor_id": floor_id,
        "location_x": 50,
        "location_y": 50,
        "label": label,
    }
    if logo_icon:
        new_logo["logo_icon"] = logo_icon
    floor_logos.setdefault(floor_id, []).append(new_logo)
    settings["floor_plan_logos"] = floor_logos
    settings_service.save_settings(settings)
    return jsonify(new_logo)


@app.post("/api/floor-logos/<logo_id>/position")
def update_floor_logo_position(logo_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(silent=True) or {}
    try:
        location_x = float(payload.get("location_x"))
        location_y = float(payload.get("location_y"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid coordinates"}), 400
    location_x = max(0, min(100, location_x))
    location_y = max(0, min(100, location_y))
    settings = settings_service.load_settings()
    floor_logos = settings.get("floor_plan_logos", {})
    for floor_id, logos in floor_logos.items():
        for logo in logos:
            if logo.get("logo_id") == logo_id:
                logo["location_x"] = location_x
                logo["location_y"] = location_y
                logo["floor_id"] = floor_id
                settings["floor_plan_logos"] = floor_logos
                settings_service.save_settings(settings)
                return jsonify(logo)
    return jsonify({"error": "Logo not found"}), 404


@app.post("/api/floor-logos/<logo_id>/label")
def update_floor_logo_label(logo_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(silent=True) or {}
    label = (payload.get("label") or "").strip()
    settings = settings_service.load_settings()
    floor_logos = settings.get("floor_plan_logos", {})
    for floor_id, logos in floor_logos.items():
        for logo in logos:
            if logo.get("logo_id") == logo_id:
                logo["label"] = label
                logo["floor_id"] = floor_id
                settings["floor_plan_logos"] = floor_logos
                settings_service.save_settings(settings)
                return jsonify(logo)
    return jsonify({"error": "Logo not found"}), 404


@app.post("/api/ingest/milesight")
def ingest_milesight():
    payload = request.get_json(silent=True) or {}
    settings = settings_service.load_settings()
    ingest_token = settings.get("ingest_token")
    if ingest_token:
        if request.headers.get("X-API-Key") != ingest_token:
            return jsonify({"error": "Unauthorized"}), 403
    result = data_service.ingest_milesight_payload(payload)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.delete("/api/floor-logos/<logo_id>")
def delete_floor_logo(logo_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    settings = settings_service.load_settings()
    floor_logos = settings.get("floor_plan_logos", {})
    removed = False
    for floor_id in list(floor_logos.keys()):
        logos = floor_logos[floor_id]
        updated = [logo for logo in logos if logo.get("logo_id") != logo_id]
        if len(updated) != len(logos):
            removed = True
            if updated:
                floor_logos[floor_id] = updated
            else:
                floor_logos.pop(floor_id, None)
    if removed:
        settings["floor_plan_logos"] = floor_logos
        settings_service.save_settings(settings)
    return jsonify({"logo_id": logo_id, "removed": removed})


@app.route("/login", methods=["GET", "POST"])
def login():
    settings = settings_service.load_settings()
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == settings.get("admin_username") and password == settings.get("admin_password"):
            session["is_admin"] = True
            return redirect(url_for("index"))
        error = "Invalid credentials"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
