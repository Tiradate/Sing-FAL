import csv
import os
from datetime import datetime

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
from services.db import init_all, seed_demo_data


app = Flask(__name__)
app.secret_key = "replace-with-secure-secret"

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


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

    daily_labels, daily_values = data_service.get_daily_series("pm25", floor_id=floor_id)
    weekly_labels, weekly_values = data_service.get_weekly_series("pm25", floor_id=floor_id)

    sensor_cards = data_service.get_latest_avg_metrics(floor_id=floor_id)
    indoor_outdoor = data_service.get_latest_indoor_outdoor(floor_id=floor_id)
    indoor_outdoor_aqi = data_service.get_indoor_outdoor_aqi(floor_id=floor_id)

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
        sensor_cards=sensor_cards,
        indoor_outdoor=indoor_outdoor,
        indoor_outdoor_aqi=indoor_outdoor_aqi,
        now=datetime.now(),
        status_label=data_service.aggregate_status_label(settings),
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


@app.route("/graphs/daily")
def graphs_daily():
    metric = request.args.get("metric", "pm25")
    floor_id = request.args.get("floor")
    labels, values = data_service.get_daily_series(metric, floor_id)
    if request.args.get("format") == "json":
        return jsonify({"labels": labels, "values": values})
    return render_template("graphs_daily.html", labels=labels, values=values, metric=metric)


@app.route("/graphs/weekly")
def graphs_weekly():
    metric = request.args.get("metric", "pm25")
    floor_id = request.args.get("floor")
    labels, values = data_service.get_weekly_series(metric, floor_id)
    if request.args.get("format") == "json":
        return jsonify({"labels": labels, "values": values})
    return render_template("graphs_weekly.html", labels=labels, values=values, metric=metric)


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

        if "floor_plan" in request.files:
            file = request.files["floor_plan"]
            floor_id = request.form.get("floor_id")
            if file and file.filename and floor_id:
                filename = secure_filename(file.filename)
                path = os.path.join(UPLOAD_DIR, filename)
                file.save(path)
                settings["floor_plans"][floor_id] = f"static/uploads/{filename}"

        settings_service.save_settings(settings)
        return redirect(url_for("settings"))

    return render_template("settings.html", settings=settings)


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
