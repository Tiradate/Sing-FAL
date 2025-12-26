import csv
import io
import json
import os
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
    }


@app.route("/")
def index():
    settings = settings_service.load_settings()
    floors = data_service.get_floor_list()
    floor_id = request.args.get("floor") or (floors[0] if floors else None)
    devices = data_service.get_devices()
    alarm_severity = data_service.get_device_alarm_severity()
    active_alarms = data_service.get_active_alarms()
    metric_options = data_service.get_metric_options()
    metric_option_map = {option["key"]: {"label": option["label"], "unit": option["unit"]} for option in metric_options}
    daily_metric = request.args.get("daily_metric", "pm25")
    weekly_metric = request.args.get("weekly_metric", "pm25")

    daily_labels, daily_values = data_service.get_daily_series(daily_metric, floor_id=floor_id)
    weekly_labels, weekly_values = data_service.get_weekly_series(weekly_metric, floor_id=floor_id)

    sensor_cards = data_service.get_latest_avg_metrics(floor_id=floor_id)
    indoor_outdoor = data_service.get_latest_indoor_outdoor(floor_id=floor_id)
    indoor_outdoor_aqi = data_service.get_indoor_outdoor_aqi(floor_id=floor_id)
    device_metrics = data_service.get_latest_device_metrics(floor_id=floor_id)

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
        floors=floors,
        active_floor=floor_id,
        devices=devices,
        alarm_severity=alarm_severity,
        active_alarms=active_alarms,
        daily_labels=daily_labels,
        daily_values=daily_values,
        weekly_labels=weekly_labels,
        weekly_values=weekly_values,
        daily_metric=daily_metric,
        weekly_metric=weekly_metric,
        sensor_cards=sensor_cards,
        indoor_outdoor=indoor_outdoor,
        indoor_outdoor_aqi=indoor_outdoor_aqi,
        device_metrics=device_metrics,
        metric_options=metric_options,
        metric_option_map=metric_option_map,
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
    floors = data_service.get_floor_list()
    floor_id = request.args.get("floor") or (floors[0] if floors else None)
    devices = data_service.get_devices()
    alarm_severity = data_service.get_device_alarm_severity()
    metric_options = data_service.get_metric_options()
    device_metrics = data_service.get_latest_device_metrics(floor_id=floor_id)
    return render_template(
        "map_full.html",
        floors=floors,
        active_floor=floor_id,
        devices=devices,
        alarm_severity=alarm_severity,
        metric_options=metric_options,
        device_metrics=device_metrics,
    )


@app.route("/export/sensor.csv")
def export_sensor_csv():
    rows = data_service.get_sensor_readings_csv()
    csv_path = os.path.join(BASE_DIR, "sensor_export.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts", "device_id", "floor_id", "metric", "value", "unit"])
        for row in rows:
            writer.writerow([row["ts"], row["device_id"], row["floor_id"], row["metric"], row["value"], row["unit"]])
    return send_file(csv_path, as_attachment=True, download_name="sensor_readings.csv")


@app.route("/settings/export.csv")
def export_settings_csv():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    settings = settings_service.load_settings()
    csv_path = os.path.join(BASE_DIR, "settings_export.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["key", "value"])
        for key, value in settings.items():
            writer.writerow([key, json.dumps(value)])
    return send_file(csv_path, as_attachment=True, download_name="settings.csv")


@app.route("/view_data")
def view_data():
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
        SELECT ts, device_id, metric, value, unit
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
        key = (bucket, row["metric"], row["unit"])
        if key not in aggregates:
            aggregates[key] = {"sum": 0.0, "count": 0}
        aggregates[key]["sum"] += float(value)
        aggregates[key]["count"] += 1

    metric_order = {metric: idx for idx, metric in enumerate(data_service.METRIC_ORDER)}
    records = []
    for (bucket, metric, unit), stats in sorted(
        aggregates.items(),
        key=lambda item: (item[0][0], metric_order.get(item[0][1], 999)),
    ):
        avg_value = stats["sum"] / stats["count"]
        records.append(
            {
                "timestamp": bucket.strftime("%d/%m/%Y %I:%M %p"),
                "gateway": "N/A",
                "topic": "N/A",
                "device": device,
                "tag": data_service.get_metric_label(metric),
                "value": round(avg_value, 2),
                "unit": unit,
            }
        )

    start_display = start_dt.strftime("%Y-%m-%dT%H:%M")
    end_display = end_dt.strftime("%Y-%m-%dT%H:%M")
    devices = data_service.get_devices()

    return render_template(
        "view_data.html",
        data=records,
        start_datetime=start_display,
        end_datetime=end_display,
        active_device=device,
        interval_minutes=interval_minutes,
        devices=devices,
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
    active_alarms = data_service.get_active_alarms()
    history = data_service.get_alarm_history()
    today = datetime.utcnow().date().isoformat()
    action_start = request.args.get("action_start") or today
    action_end = request.args.get("action_end") or today
    action_history = data_service.get_action_history(action_start, action_end)
    return render_template(
        "alarms.html",
        active_alarms=active_alarms,
        history=history,
        action_history=action_history,
        action_start=action_start,
        action_end=action_end,
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


@app.route("/alarms/actions.csv")
def export_action_history():
    today = datetime.utcnow().date().isoformat()
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
    available_uploads = []
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(path):
                available_uploads.append(f"static/uploads/{filename}")
    available_uploads.sort()
    if request.method == "POST":
        settings["project_name"] = request.form.get("project_name", settings["project_name"])
        settings["location_label"] = request.form.get("location_label", settings["location_label"])
        settings["floor_auto_rotate_seconds"] = int(
            request.form.get("floor_auto_rotate_seconds", settings["floor_auto_rotate_seconds"])
        )
        settings["sensor_icon_size"] = int(
            request.form.get("sensor_icon_size", settings["sensor_icon_size"])
        )
        settings["show_icons"] = {
            "bell": bool(request.form.get("show_bell")),
            "calendar": bool(request.form.get("show_calendar")),
            "download": bool(request.form.get("show_download")),
            "settings": True,
        }

        severity_labels = request.form.getlist("severity_label")
        severity_colors = request.form.getlist("severity_color")
        severity_icons = request.form.getlist("severity_icon")
        severity_levels = []
        for label, color, icon in zip(severity_labels, severity_colors, severity_icons):
            if label.strip():
                severity_levels.append({"label": label.strip(), "color": color, "icon": icon})
        settings["severity_levels"] = severity_levels
        settings["critical_levels"] = request.form.getlist("critical_levels")

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

        floor_ids = request.form.getlist("floor_id")
        floor_files = request.files.getlist("floor_plan")
        floor_existing = request.form.getlist("floor_plan_existing")
        updated_floor_plans = {}
        for index, floor_id in enumerate(floor_ids):
            floor_id = floor_id.strip()
            if not floor_id:
                continue
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

        if updated_floor_plans:
            settings["floor_plans"] = updated_floor_plans

        settings_service.save_settings(settings)
        return redirect(url_for("settings"))

    return render_template("settings.html", settings=settings, available_uploads=available_uploads)


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
