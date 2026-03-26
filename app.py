import csv
import base64
import hashlib
import io
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from datetime import datetime, timedelta, timezone
from functools import wraps
from shutil import which
from zoneinfo import ZoneInfo


BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _venv_python_path(venv_path):
    if os.name == "nt":
        return os.path.join(venv_path, "Scripts", "python.exe")

    python3_path = os.path.join(venv_path, "bin", "python3")
    if os.path.exists(python3_path):
        return python3_path

    return os.path.join(venv_path, "bin", "python")


def _create_virtualenv(venv_path):
    commands = [
        [sys.executable, "-m", "venv", "--system-site-packages", venv_path],
        [sys.executable, "-m", "venv", venv_path],
    ]

    for command in commands:
        try:
            subprocess.check_call(command)
            return True
        except subprocess.CalledProcessError as exc:
            print(f"[startup] Virtual environment creation failed for '{' '.join(command)}': {exc}")

    return False


def _requirements_hash(requirements_path):
    with open(requirements_path, "rb") as requirements_file:
        return hashlib.sha256(requirements_file.read()).hexdigest()


def _requirements_satisfied(requirements_path):
    with open(requirements_path, "r", encoding="utf-8") as requirements_file:
        for raw_line in requirements_file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if "==" not in line:
                return False

            package_name, expected_version = [part.strip() for part in line.split("==", 1)]
            try:
                installed_version = importlib.metadata.version(package_name)
            except importlib.metadata.PackageNotFoundError:
                return False

            if installed_version != expected_version:
                return False

    return True


def _has_pip():
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _bootstrap_pip():
    try:
        subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])
        return _has_pip()
    except subprocess.CalledProcessError as exc:
        print(f"[startup] ensurepip bootstrap failed ({exc}).")
        return False


def _install_system_python_packages():
    if sys.platform != "linux" or which("apt-get") is None:
        return False

    os_release_path = "/etc/os-release"
    try:
        with open(os_release_path, "r", encoding="utf-8") as os_release_file:
            os_release = os_release_file.read().lower()
    except OSError:
        return False

    if "debian" not in os_release and "ubuntu" not in os_release:
        return False

    commands = [
        ["apt-get", "update"],
        ["apt-get", "install", "-y", "python3-pip", "python3-venv"],
    ]

    for command in commands:
        try:
            subprocess.check_call(command)
        except subprocess.CalledProcessError as exc:
            print(
                "[startup] Warning: automatic system package installation failed "
                f"for '{' '.join(command)}' ({exc})."
            )
            return False

    return True

def ensure_runtime_environment():
    requirements_path = os.path.join(BASE_DIR, "requirements.txt")
    if not os.path.exists(requirements_path):
        print(f"[startup] requirements.txt not found at {requirements_path}. Skipping dependency sync.")
        return

    in_virtualenv = (
        hasattr(sys, "real_prefix")
        or getattr(sys, "base_prefix", sys.prefix) != sys.prefix
        or bool(os.environ.get("VIRTUAL_ENV"))
    )
    venv_path = os.path.join(BASE_DIR, ".venv")
    venv_python = _venv_python_path(venv_path)

    if not in_virtualenv:
        if not os.path.exists(venv_python):
            print(f"[startup] Virtual environment not found. Creating one at {venv_path}...")
            if not _create_virtualenv(venv_path):
                print(
                    "[startup] Warning: unable to create virtual environment on this system. "
                    "Continuing with the current Python interpreter."
                )
                venv_python = os.path.abspath(sys.executable)
            else:
                venv_python = _venv_python_path(venv_path)

        if os.path.abspath(sys.executable) != os.path.abspath(venv_python):
            print("[startup] Re-launching app using virtual environment interpreter...")
            subprocess.check_call([venv_python, os.path.abspath(__file__), *sys.argv[1:]])
            sys.exit(0)

    if _requirements_satisfied(requirements_path):
        print("[startup] Runtime dependencies are already available.")
        return

    state_path = os.path.join(BASE_DIR, ".runtime_env_state.json")
    runtime_key = {
        "python": os.path.abspath(sys.executable),
        "requirements_hash": _requirements_hash(requirements_path),
    }

    try:
        with open(state_path, "r", encoding="utf-8") as state_file:
            existing_state = json.load(state_file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        existing_state = {}

    if existing_state == runtime_key:
        print("[startup] Runtime dependencies are already synchronized.")
        return

    if not _has_pip():
        print("[startup] pip is unavailable; attempting to bootstrap with ensurepip...")
        if _bootstrap_pip():
            print("[startup] pip installation succeeded.")
        else:
            print("[startup] ensurepip was unavailable; attempting to install python3-pip/python3-venv...")
            if _install_system_python_packages() and _has_pip():
                print("[startup] pip installation succeeded.")
            else:
                print(
                    "[startup] Warning: pip is unavailable and could not be installed automatically. "
                    "Dependency synchronization skipped."
                )
                return

    try:
        print("[startup] Updating pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])

        print("[startup] Installing dependencies from requirements.txt...")
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "-r",
                requirements_path,
            ]
        )
    except subprocess.CalledProcessError as exc:
        print(f"[startup] Warning: dependency synchronization failed ({exc}). Continuing startup.")
        return

    with open(state_path, "w", encoding="utf-8") as state_file:
        json.dump(runtime_key, state_file)


if not _env_flag("ICON_SKIP_RUNTIME_BOOTSTRAP", default=False):
    ensure_runtime_environment()

from flask import (
    Flask,
    flash,
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
from services import auth as auth_service
from services import settings as settings_service
from services.api_history import (
    delete_api_request_history,
    export_api_request_history,
    latest_api_request_history,
    list_api_request_history,
    log_api_request_history,
)
from services.db import SENSOR_DB, connect, init_all, seed_demo_data


app = Flask(__name__)
app.secret_key = os.environ.get("ICON_SECRET_KEY", "replace-with-secure-secret")

_BACKGROUND_SOURCE_POLLING_LOCK = threading.Lock()
_BACKGROUND_SOURCE_POLLING_STATE_LOCK = threading.Lock()
_BACKGROUND_SOURCE_POLLING_THREAD = None
_BACKGROUND_SOURCE_POLLING_STATE = {}
_SOURCE_REQUEST_HISTORY_JOB_LOCK = threading.Lock()
_SOURCE_REQUEST_HISTORY_JOBS = {}
_SOURCE_REQUEST_HISTORY_JOB_RETENTION_SECONDS = 15 * 60
_SOURCE_REQUEST_HISTORY_EXPORT_DIR = os.path.join(
    BASE_DIR,
    "tmp",
    "source_request_history_exports",
)
os.makedirs(_SOURCE_REQUEST_HISTORY_EXPORT_DIR, exist_ok=True)

SUPPORTED_LANGUAGES = {
    "en": "ENG",
    "th": "THA",
}

TRANSLATIONS = {
    "en": {
        "home": "Home",
        "notifications": "Notifications",
        "download": "Download",
        "settings": "Settings",
        "logout": "Logout",
        "language": "Language",
        "signal": "Signal",
        "critical_alarm": "Critical alarm detected. Immediate attention required.",
        "login": "Login",
        "admin_login": "Admin Login",
        "username": "Username",
        "password": "Password",
        "home_page_for_guest": "Home page for guest",
        "invalid_credentials": "Invalid credentials",
        "sensor_data_explorer": "Sensor Data Explorer",
        "records": "records",
        "device": "Device",
        "start": "Start",
        "end": "End",
        "interval": "Interval",
        "minutes_short": "min",
        "filter": "Filter",
        "admin_data_tools": "Admin Data Tools",
        "delete_current_data_range": "Delete current data range",
        "confirm_delete_selected_range": "Delete data for the selected device and range?",
        "delete_data": "Delete Data",
        "test_data_controls": "Test data controls",
        "start_date": "Start date",
        "end_date": "End date",
        "seed_test_data": "Seed Test Data",
        "confirm_delete_test_data": "Delete test data?",
        "delete_test_data": "Delete Test Data",
        "test_data_note": "Test data is tagged with topic \"Test\" and seeded for all devices.",
        "timestamp": "Timestamp",
        "gateway": "Gateway",
        "topic": "Topic",
        "no_data_for_range": "No data available for this range.",
        "top_definition": "Top Definition",
        "color_definition": "Color Definition",
        "average_indoor_outdoor_iaq": "Average Indoor/Outdoor IAQ",
        "average_indoor_outdoor": "Average Indoor/Outdoor",
        "indoor": "Indoor",
        "outdoor": "Outdoor",
        "good": "Good",
        "moderate": "Moderate",
        "unhealthy": "Unhealthy",
        "critical": "Critical",
        "map": "Map",
        "floor_plan_sensors": "Floor plan & sensors",
        "expand": "Expand",
        "unassigned": "Unassigned",
        "occupied": "Occupied",
        "vacant": "Vacant",
        "hover_sensor_details": "Hover or tap a sensor to view details.",
        "daily_graph": "Daily Graph",
        "timeline_24h": "24-hour timeline",
        "view_data": "View data",
        "last_24_hours": "Last 24 hours",
        "all_data": "All data",
        "all_devices": "All devices",
        "today": "Today",
        "weekly_overview": "Weekly Overview",
        "average_per_day": "Average per day",
        "last_7_days": "Last 7 days",
        "alerts_notifications": "Alerts & Notifications",
        "see_all_alarm": "See all alarm",
        "no_active_alarms": "No active alarms.",
        "auto": "Auto",
        "upload_floor_plan_settings": "Upload a floor plan in settings",
        "user_manage": "User Manage",
        "add_user": "Add User",
        "full_name": "Full Name",
        "name": "Name",
        "role": "Role",
        "last_login": "Last Login",
        "new_password": "New Password",
        "action": "Action",
        "save_role": "Save Role",
        "change_password": "Change Password",
        "delete": "Delete",
        "manage_users": "Manage Users",
        "change_passwords_or_delete_users": "Change passwords or delete users.",
        "role_permissions": "Role Permissions",
        "check_pages_each_role_can_see": "Check pages that each role can see.",
        "add_role": "Add Role",
        "can_see": "Can See",
        "save": "Save",
        "login_history": "Login History",
        "time": "Time",
        "status": "Status",
        "location": "Location",
        "request": "Request",
        "user_agent": "User Agent",
        "no_login_history_yet": "No login history yet.",
    },
    "th": {
        "signal": "สัญญาณ",
        "home": "หน้าแรก",
        "notifications": "การแจ้งเตือน",
        "download": "ดาวน์โหลด",
        "settings": "ตั้งค่า",
        "logout": "ออกจากระบบ",
        "language": "ภาษา",
        "critical_alarm": "พบสัญญาณเตือนระดับวิกฤต กรุณาตรวจสอบทันที",
        "login": "เข้าสู่ระบบ",
        "admin_login": "ผู้ดูแลระบบเข้าสู่ระบบ",
        "username": "ชื่อผู้ใช้",
        "password": "รหัสผ่าน",
        "home_page_for_guest": "กลับสู่หน้าแรกสำหรับผู้เยี่ยมชม",
        "invalid_credentials": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง",
        "sensor_data_explorer": "สำรวจข้อมูลเซนเซอร์",
        "records": "รายการ",
        "device": "อุปกรณ์",
        "start": "เริ่มต้น",
        "end": "สิ้นสุด",
        "interval": "ช่วงเวลา",
        "minutes_short": "นาที",
        "filter": "กรอง",
        "admin_data_tools": "เครื่องมือข้อมูลสำหรับผู้ดูแล",
        "delete_current_data_range": "ลบข้อมูลช่วงเวลาปัจจุบัน",
        "confirm_delete_selected_range": "ลบข้อมูลของอุปกรณ์และช่วงเวลาที่เลือกหรือไม่?",
        "delete_data": "ลบข้อมูล",
        "test_data_controls": "เครื่องมือข้อมูลทดสอบ",
        "start_date": "วันที่เริ่มต้น",
        "end_date": "วันที่สิ้นสุด",
        "seed_test_data": "สร้างข้อมูลทดสอบ",
        "confirm_delete_test_data": "ลบข้อมูลทดสอบหรือไม่?",
        "delete_test_data": "ลบข้อมูลทดสอบ",
        "test_data_note": "ข้อมูลทดสอบจะถูกกำหนดหัวข้อเป็น \"Test\" และสร้างให้ทุกอุปกรณ์",
        "timestamp": "เวลา",
        "gateway": "เกตเวย์",
        "topic": "หัวข้อ",
        "no_data_for_range": "ไม่มีข้อมูลสำหรับช่วงเวลานี้",
        "top_definition": "ภาพรวมด้านบน",
        "average_indoor_outdoor_iaq": "ค่าเฉลี่ย IAQ ภายใน/ภายนอก",
        "indoor": "ภายใน",
        "outdoor": "ภายนอก",
        "critical": "วิกฤต",
        "map": "แผนที่",
        "floor_plan_sensors": "ผังชั้นและเซนเซอร์",
        "expand": "ขยาย",
        "unassigned": "ยังไม่กำหนด",
        "occupied": "มีการใช้งาน",
        "vacant": "ว่าง",
        "hover_sensor_details": "เลื่อนเมาส์หรือแตะเซนเซอร์เพื่อดูรายละเอียด",
        "daily_graph": "กราฟรายวัน",
        "timeline_24h": "ไทม์ไลน์ 24 ชั่วโมง",
        "view_data": "ดูข้อมูล",
        "last_24_hours": "24 ชั่วโมงล่าสุด",
        "all_data": "ข้อมูลทั้งหมด",
        "all_devices": "ทุกอุปกรณ์",
        "today": "วันนี้",
        "weekly_overview": "ภาพรวมรายสัปดาห์",
        "average_per_day": "ค่าเฉลี่ยต่อวัน",
        "last_7_days": "7 วันล่าสุด",
        "alerts_notifications": "การแจ้งเตือน",
        "see_all_alarm": "ดูการแจ้งเตือนทั้งหมด",
        "no_active_alarms": "ไม่มีการแจ้งเตือนที่กำลังเกิดขึ้น",
    },
}

UTC_PLUS_7 = timezone(timedelta(hours=7))
PROJECT_TIMEZONE_FALLBACKS = {
    "UTC": timezone.utc,
    "Asia/Bangkok": timezone(timedelta(hours=7)),
    "Asia/Yangon": timezone(timedelta(hours=6, minutes=30)),
    "Asia/Singapore": timezone(timedelta(hours=8)),
    "Asia/Tokyo": timezone(timedelta(hours=9)),
    "Europe/London": timezone.utc,
    "America/New_York": timezone(timedelta(hours=-5)),
    "America/Los_Angeles": timezone(timedelta(hours=-8)),
}
UTC_PLUS_6_5 = timezone(timedelta(hours=6, minutes=30))
PROJECT_TIMEZONE_OPTIONS = [
    ("Asia/Bangkok", "Asia/Bangkok (UTC+07:00)"),
    ("UTC", "UTC"),
    ("Asia/Yangon", "Asia/Yangon (UTC+06:30)"),
    ("Asia/Singapore", "Asia/Singapore (UTC+08:00)"),
    ("Asia/Tokyo", "Asia/Tokyo (UTC+09:00)"),
    ("Europe/London", "Europe/London"),
    ("America/New_York", "America/New_York"),
    ("America/Los_Angeles", "America/Los_Angeles"),
]
PROJECT_TIME_FORMAT_OPTIONS = [
    ("24h", "24-hour"),
    ("12h", "12-hour"),
]


def get_project_timezone_name(settings):
    value = str((settings or {}).get("project_timezone") or "Asia/Bangkok").strip()
    if value in PROJECT_TIMEZONE_FALLBACKS:
        return value
    try:
        ZoneInfo(value)
        return value
    except Exception:
        return "Asia/Bangkok"


def get_project_timezone(settings):
    timezone_name = get_project_timezone_name(settings)
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return PROJECT_TIMEZONE_FALLBACKS.get(timezone_name, UTC_PLUS_7)


def get_project_time_format(settings):
    value = str((settings or {}).get("project_time_format") or "24h").strip().lower()
    return value if value in {"24h", "12h"} else "24h"


def get_project_date_format():
    language = get_current_language()
    if language == "th":
        return "%d/%m/%Y"
    return "%Y/%m/%d"


def format_project_datetime(value, settings):
    if not value:
        return ""
    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = datetime.fromisoformat(parsed)
        except ValueError:
            return value
    if not isinstance(parsed, datetime):
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_ts = parsed.astimezone(get_project_timezone(settings))
    date_pattern = get_project_date_format()
    time_pattern = f"{date_pattern} %H:%M" if get_project_time_format(settings) == "24h" else f"{date_pattern} %I:%M %p"
    return local_ts.strftime(time_pattern)


def format_project_datetime_seconds(value, settings):
    if not value:
        return ""
    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = datetime.fromisoformat(parsed)
        except ValueError:
            return value
    if not isinstance(parsed, datetime):
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_ts = parsed.astimezone(get_project_timezone(settings))
    date_pattern = get_project_date_format()
    time_pattern = f"{date_pattern} %H:%M:%S" if get_project_time_format(settings) == "24h" else f"{date_pattern} %I:%M:%S %p"
    return local_ts.strftime(time_pattern)


def format_project_datetime_local_input(value, settings):
    if not value:
        return ""
    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = datetime.fromisoformat(parsed)
        except ValueError:
            return value
    if not isinstance(parsed, datetime):
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_ts = parsed.astimezone(get_project_timezone(settings))
    return local_ts.strftime("%Y-%m-%dT%H:%M")

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


def _collect_upload_assets(settings, devices):
    del settings, devices

    asset_paths = []
    if not os.path.isdir(UPLOAD_DIR):
        return asset_paths

    for root, _dirs, files in os.walk(UPLOAD_DIR):
        for filename in files:
            absolute_path = os.path.join(root, filename)
            relative_name = os.path.relpath(absolute_path, UPLOAD_DIR).replace("\\", "/")
            asset_paths.append((relative_name, absolute_path))

    return sorted(asset_paths, key=lambda item: item[0].lower())


def get_enabled_metric_options(settings, system_key):
    if system_key == "fire":
        options = data_service.get_fire_metric_options()
    else:
        base_options = data_service.get_metric_options()
        source_options = [
            {
                "key": field["key"],
                "label": field.get("label") or field.get("source_field") or field["key"],
                "unit": field.get("unit") or "",
            }
            for field in data_service.get_source_metric_fields(settings)
            if field.get("save_to_db")
        ]
        merged_options = {option["key"]: option for option in base_options}
        for option in source_options:
            merged_options[option["key"]] = option
        options = list(merged_options.values())
    visibility = settings.get("tag_visibility", {}).get(system_key, {})
    if isinstance(visibility, dict) and visibility:
        filtered = [
            option
            for option in options
            if option["key"] not in visibility or visibility.get(option["key"], False)
        ]
        if filtered:
            return filtered
    return options


def get_configured_severity_metric_keys(settings):
    metric_keys = set()
    for level in settings.get("severity_levels", []):
        thresholds = level.get("thresholds", {})
        if not isinstance(thresholds, dict):
            continue
        for metric, threshold in thresholds.items():
            if threshold is None:
                continue
            metric_key = str(metric or "").strip()
            if metric_key:
                metric_keys.add(metric_key)
    return sorted(metric_keys)


def extract_sensor_type_from_label(label):
    segments = [segment.strip() for segment in str(label or "").split("-") if segment.strip()]
    return segments[3] if len(segments) >= 4 else ""


def get_device_sensor_type_keys(devices):
    metric_keys = set()
    for device in devices or []:
        sensor_types = device.get("sensor_types") if hasattr(device, "get") else None
        for metric_key in data_service.parse_device_sensor_types(sensor_types):
            if metric_key:
                metric_keys.add(metric_key)
    return sorted(metric_keys)


def record_value(record, key, default=None):
    if hasattr(record, "get"):
        return record.get(key, default)
    try:
        return record[key]
    except (KeyError, TypeError):
        return default


def get_request_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    for header_name in ("X-Real-IP", "CF-Connecting-IP"):
        header_value = request.headers.get(header_name)
        if header_value:
            return header_value.strip()
    return request.remote_addr or ""


def get_request_location_text():
    location_bits = []
    for header_name in ("CF-IPCountry", "X-Country-Code", "X-Country", "X-Region", "X-City"):
        header_value = str(request.headers.get(header_name) or "").strip()
        if header_value:
            location_bits.append(header_value)
    return ", ".join(location_bits)


ROLE_PAGE_KEYS = ("home", "alarms", "map", "settings")


def get_role_page_access_map(settings=None):
    resolved_settings = settings if settings is not None else settings_service.load_settings()
    role_permissions = resolved_settings.get("role_permissions", {})
    access_map = {}
    for role_name, page_permissions in role_permissions.items():
        normalized_role = auth_service.normalize_role(role_name)
        access_map[normalized_role] = {
            page_key
            for page_key in ROLE_PAGE_KEYS
            if isinstance(page_permissions, dict) and bool(page_permissions.get(page_key))
        }
    if "admin" not in access_map:
        access_map["admin"] = set(ROLE_PAGE_KEYS)
    return access_map


def get_current_role():
    return str(session.get("role") or ("admin" if session.get("is_admin") else "user")).strip().lower()


def has_page_access(page_key):
    role = get_current_role()
    allowed_pages = get_role_page_access_map().get(role, set())
    return page_key in allowed_pages


def get_first_accessible_endpoint(settings=None):
    role = get_current_role()
    allowed_pages = get_role_page_access_map(settings).get(role, set())
    if "map" in allowed_pages or not session.get("user_id"):
        return "map_full"
    if "home" in allowed_pages:
        return "index"
    if "alarms" in allowed_pages:
        return "alarms"
    if "settings" in allowed_pages:
        return "settings"
    return "map_full"


def require_page_access(page_key):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if page_key == "map":
                return func(*args, **kwargs)
            if not session.get("user_id") and not session.get("is_admin"):
                return redirect(url_for("login"))
            if not has_page_access(page_key):
                return redirect(url_for(get_first_accessible_endpoint()))
            return func(*args, **kwargs)
        return wrapper
    return decorator


def device_value(device, key, default=None):
    return record_value(device, key, default)


def normalize_floor_id(value):
    if value is None:
        return ""
    return str(value).strip()


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
    _ensure_background_source_polling_started()


def get_current_language():
    language = session.get("lang", "en")
    if language not in SUPPORTED_LANGUAGES:
        return "en"
    return language


def translate_text(key):
    language = get_current_language()
    default_messages = TRANSLATIONS["en"]
    language_messages = TRANSLATIONS.get(language, default_messages)
    return language_messages.get(key, default_messages.get(key, key))


ALARM_MESSAGE_TRANSLATIONS_TH = {
    "Temperature": "อุณหภูมิ",
    "Humidity": "ความชื้น",
    "Smoke": "ควัน",
    "Heat": "ความร้อน",
    "Flow Switch": "โฟลว์สวิตช์",
    "Supervisory valve": "วาล์วควบคุม",
    "Manual": "ปุ่มกดแจ้งเหตุ",
    "Gas": "ก๊าซ",
}


def translate_alarm_message(message):
    text = str(message or "").strip()
    if not text or get_current_language() != "th":
        return text
    translated = text
    for source, target in ALARM_MESSAGE_TRANSLATIONS_TH.items():
        translated = re.sub(rf"\b{re.escape(source)}\b", target, translated)
    translated = translated.replace(" exceeds ", " เกิน ")
    translated = translated.replace(" is above the limit", " สูงกว่าค่าที่กำหนด")
    return translated


@app.context_processor
def inject_globals():
    settings = settings_service.load_settings()
    auth_service.ensure_default_admin_user(settings)
    active_alarms = data_service.get_active_alarms()
    critical_levels = settings.get("critical_levels", [])
    return {
        "settings": settings,
        "is_admin": session.get("is_admin", False),
        "current_role": get_current_role(),
        "has_page_access": has_page_access,
        "alarm_count": data_service.get_alarm_count(),
        "calendar_value": data_service.get_calendar_value(),
        "avg_signal": data_service.get_avg_signal_quality(),
        "has_critical": any(alarm["severity"] in critical_levels for alarm in active_alarms),
        "current_system": resolve_active_system(settings),
        "current_lang": get_current_language(),
        "supported_languages": SUPPORTED_LANGUAGES,
        "project_timezone_options": PROJECT_TIMEZONE_OPTIONS,
        "project_time_format_options": PROJECT_TIME_FORMAT_OPTIONS,
        "format_project_datetime": lambda value: format_project_datetime(value, settings),
        "t": translate_text,
        "translate_alarm_message": translate_alarm_message,
    }


@app.route("/set-language/<lang>")
def set_language(lang):
    normalized = (lang or "").strip().lower()
    session["lang"] = normalized if normalized in SUPPORTED_LANGUAGES else "en"

    next_url = request.args.get("next")
    if next_url:
        return redirect(next_url)
    return redirect(url_for("map_full"))


@app.route("/")
def home():
    return redirect(url_for("map_full"))


@app.route("/dashboard")
@require_page_access("home")
def index():
    settings = settings_service.load_settings()
    active_system = resolve_active_system(settings)
    floors = data_service.get_floor_list()
    floor_param = request.args.get("floor")
    floor_id = floor_param or (floors[0] if floors else None)
    devices = data_service.get_devices()
    alarm_severity = data_service.get_device_alarm_severity()
    active_alarms = data_service.get_active_alarms(floor_id=floor_id)
    all_active_alarms = data_service.get_active_alarms()

    device_label_map = {}
    for device in devices:
        device_id = record_value(device, "device_id")
        if device_id:
            device_label_map[device_id] = record_value(device, "label")
    metric_options = get_enabled_metric_options(settings, active_system)
    metric_option_map = {
        option["key"]: {"label": option["label"], "unit": option["unit"]}
        for option in metric_options
    }
    metric_keys = [option["key"] for option in metric_options]
    tooltip_metric_options = (
        data_service.get_tooltip_metric_options(settings)
        if active_system != "fire"
        else metric_options
    )
    if active_system != "fire":
        tooltip_option_map = {option["key"]: option for option in tooltip_metric_options}
        source_field_map = {
            field["key"]: field for field in data_service.get_source_metric_fields(settings)
        }
        for metric_key in get_device_sensor_type_keys(devices):
            if metric_key in tooltip_option_map:
                continue
            field = source_field_map.get(metric_key)
            if not field:
                continue
            tooltip_option_map[metric_key] = {
                "key": metric_key,
                "label": field.get("label") or field.get("source_field") or metric_key,
                "unit": field.get("unit") or "",
            }
        tooltip_metric_options = list(tooltip_option_map.values())
    if active_system != "fire":
        tooltip_option_map = {option["key"]: option for option in tooltip_metric_options}
        source_field_map = {
            field["key"]: field for field in data_service.get_source_metric_fields(settings)
        }
        for metric_key in get_device_sensor_type_keys(devices):
            if metric_key in tooltip_option_map:
                continue
            field = source_field_map.get(metric_key)
            if not field:
                continue
            tooltip_option_map[metric_key] = {
                "key": metric_key,
                "label": field.get("label") or field.get("source_field") or metric_key,
                "unit": field.get("unit") or "",
            }
        tooltip_metric_options = list(tooltip_option_map.values())
    tooltip_metric_keys = [option["key"] for option in tooltip_metric_options]
    severity_metric_keys = sorted(
        set(
            tooltip_metric_keys
            + get_configured_severity_metric_keys(settings)
            + [
                field["key"]
                for field in data_service.get_source_metric_fields(settings)
                if field.get("enable_severity")
            ]
        )
    )
    fallback_metric = metric_keys[0] if metric_keys else "pm25"
    daily_metric = request.args.get("daily_metric") or fallback_metric
    weekly_metric = request.args.get("weekly_metric") or fallback_metric
    if daily_metric not in metric_keys:
        daily_metric = fallback_metric
    if weekly_metric not in metric_keys:
        weekly_metric = fallback_metric

    project_tz = get_project_timezone(settings)
    daily_labels, daily_values = data_service.get_daily_series(
        daily_metric,
        floor_id=floor_id,
        series_timezone=project_tz,
    )
    weekly_labels, weekly_values = data_service.get_weekly_series(
        weekly_metric,
        floor_id=floor_id,
        series_timezone=project_tz,
    )

    sensor_cards = data_service.get_latest_avg_metrics(
        floor_id=floor_id,
        metrics=metric_keys,
    )
    sensor_card_severity = {
        metric: data_service.get_metric_severity(settings, metric, data.get("value"))
        for metric, data in sensor_cards.items()
    }
    indoor_outdoor = data_service.get_latest_indoor_outdoor(floor_id=floor_id)
    indoor_outdoor_aqi = data_service.get_indoor_outdoor_aqi(floor_id=floor_id)
    monitor_metric_keys = sorted(set((severity_metric_keys or metric_keys) + get_device_sensor_type_keys(devices)))
    device_metrics = data_service.get_latest_device_metrics(
        floor_id=floor_id,
        metrics=monitor_metric_keys,
    )
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
    psychro_points = []
    for device in devices:
        did = device_value(device, "device_id")
        label = device_value(device, "label") or did
        m = device_metrics.get(did, {})
        t_val = (m.get("temperature") or {}).get("value")
        h_val = (m.get("humidity") or {}).get("value")
        if t_val is not None and h_val is not None:
            psychro_points.append({
                "x": round(float(t_val), 1),
                "y": round(float(h_val), 1),
                "label": label,
            })
    critical_levels = set(settings.get("critical_levels", []))
    if metric_keys:
        active_alarms = [alarm for alarm in active_alarms if alarm["metric"] in metric_keys]

    latest_alarm_id = None
    if all_active_alarms:
        latest_alarm_id = max(
            (
                record_value(alarm, "id")
                for alarm in all_active_alarms
                if record_value(alarm, "id") is not None
            ),
            default=None,
        )

    def format_alarm_time(timestamp):
        return format_project_datetime(timestamp, settings)

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
    daily_view_end = datetime.now(project_tz)
    daily_view_start = daily_view_end - timedelta(hours=24)
    weekly_view_end = datetime.now(project_tz)
    weekly_view_start = weekly_view_end - timedelta(days=7)
    all_data_start, all_data_end = data_service.get_sensor_time_bounds(floor_id=floor_id)
    device_data_start = None
    device_data_end = None
    if default_view_device:
        device_data_start, device_data_end = data_service.get_sensor_time_bounds(
            device_id=default_view_device
        )
    if not all_data_start or not all_data_end:
        all_data_start, all_data_end = daily_view_start, daily_view_end
    elif all_data_start.tzinfo is None and all_data_end.tzinfo is None:
        all_data_start = all_data_start.replace(tzinfo=timezone.utc).astimezone(project_tz)
        all_data_end = all_data_end.replace(tzinfo=timezone.utc).astimezone(project_tz)
    if device_data_start and device_data_end:
        if device_data_start.tzinfo is None and device_data_end.tzinfo is None:
            device_data_start = device_data_start.replace(tzinfo=timezone.utc).astimezone(project_tz)
            device_data_end = device_data_end.replace(tzinfo=timezone.utc).astimezone(project_tz)
        daily_view_end = device_data_end
        daily_view_start = daily_view_end - timedelta(hours=24)
        weekly_view_end = device_data_end
        weekly_view_start = weekly_view_end - timedelta(days=7)
    return render_template(
        "index.html",
        active_system=active_system,
        floors=floors,
        active_floor=floor_id,
        floor_from_query=bool(floor_param),
        devices=devices,
        alarm_severity=alarm_severity,
        active_alarms=active_alarms,
        latest_alarm_id=latest_alarm_id,
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
        tooltip_metric_options=tooltip_metric_options,
        metric_option_map=metric_option_map,
        device_metric_severity=device_metric_severity,
        device_severity=device_severity,
        indoor_critical_count=indoor_critical_count,
        outdoor_critical_count=outdoor_critical_count,
        now=datetime.now(project_tz),
        default_view_device=default_view_device,
        daily_view_start=format_project_datetime_local_input(daily_view_start, settings),
        daily_view_end=format_project_datetime_local_input(daily_view_end, settings),
        weekly_view_start=format_project_datetime_local_input(weekly_view_start, settings),
        weekly_view_end=format_project_datetime_local_input(weekly_view_end, settings),
        all_data_start=format_project_datetime_local_input(all_data_start, settings),
        all_data_end=format_project_datetime_local_input(all_data_end, settings),
        status_label=data_service.aggregate_status_label(settings),
        psychro_points=psychro_points,
    )


@app.get("/api/alarms/status")
@require_page_access("alarms")
def alarm_status():
    settings = settings_service.load_settings()
    active_alarms = data_service.get_active_alarms()
    critical_levels = set(settings.get("critical_levels", []))
    latest_alarm_id = None
    if active_alarms:
        latest_alarm_id = max(
            (
                record_value(alarm, "id")
                for alarm in active_alarms
                if record_value(alarm, "id") is not None
            ),
            default=None,
        )
    return jsonify(
        {
            "alarm_count": data_service.get_alarm_count(),
            "has_critical": any(
                alarm["severity"] in critical_levels for alarm in active_alarms
            ),
            "latest_alarm_id": latest_alarm_id,
        }
    )


@app.route("/map")
@require_page_access("map")
def map_full():
    settings = settings_service.load_settings()
    active_system = resolve_active_system(settings)
    floors = data_service.get_floor_list()
    floor_param = request.args.get("floor")
    floor_id = floor_param or (floors[0] if floors else None)
    devices = data_service.get_devices()
    alarm_severity = data_service.get_device_alarm_severity()
    metric_options = get_enabled_metric_options(settings, active_system)
    tooltip_metric_options = (
        data_service.get_tooltip_metric_options(settings)
        if active_system != "fire"
        else metric_options
    )
    severity_metric_keys = sorted(
        set(
            [option["key"] for option in tooltip_metric_options]
            + get_configured_severity_metric_keys(settings)
            + [
                field["key"]
                for field in data_service.get_source_metric_fields(settings)
                if field.get("enable_severity")
            ]
        )
    )
    monitor_metric_keys = sorted(
        set((severity_metric_keys or [option["key"] for option in metric_options]) + get_device_sensor_type_keys(devices))
    )
    device_metrics = data_service.get_latest_device_metrics(
        floor_id=floor_id,
        metrics=monitor_metric_keys,
    )
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
        floor_from_query=bool(floor_param),
        devices=devices,
        alarm_severity=alarm_severity,
        metric_options=metric_options,
        tooltip_metric_options=tooltip_metric_options,
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
    sensor_positions = []
    for device in devices:
        floor_id = device["floor_id"] or ""
        sensor_position = {
            "device_id": device["device_id"],
            "floor_id": floor_id,
            "location_x": device["location_x"],
            "location_y": device["location_y"],
            "source_name": device.get("source_name"),
            "source_device_name": device.get("source_device_name"),
            "source_device_uuid": device.get("source_device_uuid"),
        }
        sensor_positions.append(sensor_position)
        floor_plan_sensors.setdefault(floor_id, []).append(
            {
                "device_id": sensor_position["device_id"],
                "location_x": sensor_position["location_x"],
                "location_y": sensor_position["location_y"],
                "source_name": sensor_position["source_name"],
                "source_device_name": sensor_position["source_device_name"],
                "source_device_uuid": sensor_position["source_device_uuid"],
            }
        )
    export_settings = dict(settings)
    export_settings["floor_plan_sensors"] = floor_plan_sensors
    export_settings["sensor_positions"] = sensor_positions
    csv_path = os.path.join(BASE_DIR, "settings_export.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["key", "value"])
        for key, value in export_settings.items():
            writer.writerow([key, json.dumps(value)])
    return send_file(csv_path, as_attachment=True, download_name="settings.csv")


@app.get("/settings/login-history.csv")
def export_login_history_csv():
    if not session.get("is_admin"):
        return redirect(url_for("login"))
    try:
        start_date = _normalize_history_date_text(request.args.get("login_history_start_date"))
        end_date = _normalize_history_date_text(request.args.get("login_history_end_date"))
    except ValueError:
        return "Invalid date format", 400
    rows = auth_service.list_login_history(
        limit=None,
        start_date=start_date,
        end_date=end_date,
    )
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(
        [
            "timestamp",
            "username",
            "attempted_username",
            "success",
            "ip_address",
            "location",
            "request_method",
            "request_path",
            "user_agent",
            "session_id",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["ts"],
                row["username"] or "",
                row["attempted_username"] or "",
                "success" if row["success"] else "failed",
                row["ip_address"] or "",
                row["location_text"] or "",
                row["request_method"] or "",
                row["request_path"] or "",
                row["user_agent"] or "",
                row["session_id"] or "",
            ]
        )
    csv_bytes = io.BytesIO(csv_buffer.getvalue().encode("utf-8-sig"))
    csv_bytes.seek(0)
    filename_parts = ["login_history"]
    if start_date:
        filename_parts.append(start_date)
    if end_date:
        filename_parts.append(end_date)
    return send_file(
        csv_bytes,
        as_attachment=True,
        download_name="_".join(filename_parts) + ".csv",
        mimetype="text/csv",
    )


@app.route("/settings/export-assets.zip")
def export_settings_assets_zip():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    settings = settings_service.load_settings()
    devices = data_service.get_devices()
    assets = _collect_upload_assets(settings, devices)
    zip_path = os.path.join(BASE_DIR, "settings_assets_export.zip")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, absolute_path in assets:
            archive.write(absolute_path, arcname=filename)

    return send_file(zip_path, as_attachment=True, download_name="settings_assets.zip")


@app.route("/view_data")
def view_data():
    settings = settings_service.load_settings()
    _sync_latest_history_to_sensor_db(settings)
    active_system = resolve_active_system(settings)
    devices = data_service.get_devices()
    device_ids = [row["device_id"] for row in devices if row.get("device_id")]
    device = (request.args.get("device") or "__all__").strip() or "__all__"
    start = request.args.get("start")
    end = request.args.get("end")
    project_tz = get_project_timezone(settings)
    if device != "__all__" and device not in device_ids:
        return "Unknown device", 400
    if device == "__all__" and not device_ids:
        return "Missing required parameters", 400

    if not start or not end:
        if device == "__all__":
            device_start, device_end = data_service.get_sensor_time_bounds()
        else:
            device_start, device_end = data_service.get_sensor_time_bounds(device_id=device)
        if not device_start or not device_end:
            return "Missing required parameters", 400
        if device_start.tzinfo is None:
            device_start = device_start.replace(tzinfo=timezone.utc)
        if device_end.tzinfo is None:
            device_end = device_end.replace(tzinfo=timezone.utc)
        end_now = datetime.now(project_tz)
        end = end_now.strftime("%Y-%m-%dT%H:%M")
        start_anchor = min(device_end.astimezone(project_tz), end_now)
        start = (start_anchor - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M")

    try:
        start_dt, end_dt = parse_date_range(start, end, project_tz)
    except ValueError:
        return "Invalid date format", 400

    if end_dt < start_dt:
        return "Invalid date format", 400

    start_utc = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_dt.astimezone(timezone.utc).replace(tzinfo=None)

    query = """
        SELECT ts AS event_ts, ts, device_id, metric, value, unit, topic
        FROM sensor_readings
        WHERE ts BETWEEN ? AND ?
    """
    params = [start_utc.isoformat(), end_utc.isoformat()]
    if device == "__all__":
        placeholders = ",".join("?" for _ in device_ids)
        query += f" AND device_id IN ({placeholders})"
        params.extend(device_ids)
    else:
        query += " AND device_id = ?"
        params.append(device)
    query += " ORDER BY ts DESC"
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(query, params).fetchall()

    local_tz = project_tz
    aggregates = {}
    for row in rows:
        value = row["value"]
        if value is None or value == "" or str(value).strip().upper() == "N/A":
            continue
        ts = datetime.fromisoformat(row["event_ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        local_ts = ts.astimezone(local_tz).replace(tzinfo=None)
        topic = (row["topic"] or "Live").strip() or "Live"
        key = (local_ts, topic, row["device_id"], row["metric"])
        if key not in aggregates:
            aggregates[key] = {"sum": 0.0, "count": 0, "unit": row["unit"]}
        aggregates[key]["sum"] += float(value)
        aggregates[key]["count"] += 1

    metric_options = get_enabled_metric_options(settings, active_system)
    metric_order = [option["key"] for option in metric_options]
    records = []
    timestamp_topics = sorted(
        {(event_ts, topic, device_id) for event_ts, topic, device_id, _metric in aggregates.keys()},
        reverse=True,
    )
    for event_ts, topic, bucket_device in timestamp_topics:
        record = {
            "timestamp": format_project_datetime_seconds(event_ts.replace(tzinfo=local_tz), settings),
            "gateway": "N/A",
            "topic": topic,
            "device": bucket_device,
            "metrics": {},
        }
        for metric in metric_order:
            stats = aggregates.get((event_ts, topic, bucket_device, metric))
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

    return render_template(
        "view_data.html",
        data=records,
        start_datetime=start_display,
        end_datetime=end_display,
        start_date=start_date,
        end_date=end_date,
        active_device=device,
        devices=devices,
        metric_options=metric_options,
        all_devices_value="__all__",
    )


@app.post("/view_data/delete")
def delete_view_data():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    device = request.form.get("device")
    start = request.form.get("start")
    end = request.form.get("end")
    if not device or not start or not end:
        return redirect(url_for("view_data", device=device, start=start, end=end))

    try:
        start_dt, end_dt = parse_date_range(start, end, UTC_PLUS_7)
    except ValueError:
        return redirect(url_for("view_data", device=device, start=start, end=end))

    if end_dt < start_dt:
        return redirect(url_for("view_data", device=device, start=start, end=end))

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
        )
    )


@app.post("/settings/import")
def import_settings_csv():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    settings_file = request.files.get("settings_csv")
    assets_zip_file = request.files.get("settings_assets_zip")
    postman_collection_file = request.files.get("postman_collection")
    has_csv = bool(settings_file and settings_file.filename)
    has_zip = bool(assets_zip_file and assets_zip_file.filename)
    has_collection = bool(postman_collection_file and postman_collection_file.filename)
    if not has_csv and not has_zip and not has_collection:
        return redirect(url_for("settings"))

    if has_zip:
        try:
            with zipfile.ZipFile(assets_zip_file.stream) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    normalized_name = member.filename.replace("\\", "/").strip("/")
                    if not normalized_name:
                        continue
                    parts = [secure_filename(part) for part in normalized_name.split("/")]
                    safe_parts = [part for part in parts if part and part not in {".", ".."}]
                    if not safe_parts:
                        continue
                    target_path = os.path.join(UPLOAD_DIR, *safe_parts)
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with archive.open(member) as source, open(
                        target_path, "wb"
                    ) as destination:
                        destination.write(source.read())
        except zipfile.BadZipFile:
            return redirect(url_for("settings"))

    if has_csv:
        settings = settings_service.load_settings()
        file_content = settings_file.stream.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(file_content))

        def parse_sensor_layouts(layout_payload, floor_id_hint=None):
            layouts = []
            if isinstance(layout_payload, list):
                for sensor in layout_payload:
                    if not isinstance(sensor, dict):
                        continue
                    device_id = (sensor.get("device_id") or "").strip()
                    if not device_id:
                        continue
                    floor_id = normalize_floor_id(sensor.get("floor_id") or floor_id_hint)
                    try:
                        location_x = float(sensor.get("location_x"))
                        location_y = float(sensor.get("location_y"))
                    except (TypeError, ValueError):
                        continue
                    layouts.append(
                        {
                            "device_id": device_id,
                            "floor_id": floor_id,
                            "location_x": max(0, min(100, location_x)),
                            "location_y": max(0, min(100, location_y)),
                            "source_name": (sensor.get("source_name") or "").strip() or None,
                            "source_device_name": (
                                sensor.get("source_device_name") or ""
                            ).strip()
                            or None,
                            "source_device_uuid": (
                                sensor.get("source_device_uuid") or ""
                            ).strip()
                            or None,
                        }
                    )
            return layouts

        for row in reader:
            key = (row.get("key") or "").strip()
            value = row.get("value")
            if not key:
                continue
            if key in {"floor_plan_sensors", "sensor_positions"}:
                try:
                    layout_payload = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    continue
                if key == "sensor_positions" and isinstance(layout_payload, list):
                    data_service.upsert_device_layouts(parse_sensor_layouts(layout_payload))
                elif isinstance(layout_payload, dict):
                    layouts = []
                    for floor_id, sensors in layout_payload.items():
                        layouts.extend(parse_sensor_layouts(sensors, floor_id_hint=floor_id))
                    data_service.upsert_device_layouts(layouts)
                continue
            try:
                settings[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                settings[key] = value
        settings_service.save_settings(settings)

    if has_collection:
        try:
            settings = settings_service.load_settings()
            template = _import_postman_collection(postman_collection_file)
            existing_templates = [
                item
                for item in settings.get("endpoint_api_templates", [])
                if item.get("name") != template.get("name")
            ]
            existing_templates.append(template)
            settings["endpoint_api_templates"] = sorted(
                existing_templates,
                key=lambda item: str(item.get("name") or "").lower(),
            )
            settings_service.save_settings(settings)
        except (ValueError, json.JSONDecodeError):
            return redirect(url_for("settings"))
    return redirect(url_for("settings"))


@app.route("/graphs/daily")
@require_page_access("home")
def graphs_daily():
    settings = settings_service.load_settings()
    metric = request.args.get("metric", "pm25")
    floor_id = request.args.get("floor")
    try:
        day_offset = int(request.args.get("day_offset", 0))
    except (TypeError, ValueError):
        day_offset = 0
    day_offset = max(-30, min(0, day_offset))
    labels, values = data_service.get_daily_series(
        metric,
        floor_id,
        series_timezone=get_project_timezone(settings),
        day_offset=day_offset,
    )
    return jsonify({"labels": labels, "values": values, "day_offset": day_offset})


@app.route("/graphs/weekly")
@require_page_access("home")
def graphs_weekly():
    settings = settings_service.load_settings()
    metric = request.args.get("metric", "pm25")
    floor_id = request.args.get("floor")
    labels, values = data_service.get_weekly_series(
        metric,
        floor_id,
        series_timezone=get_project_timezone(settings),
    )
    return jsonify({"labels": labels, "values": values})


@app.route("/alarms")
@require_page_access("alarms")
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


def _parse_endpoint_sources(form_data):
    endpoint_sources_json = (form_data.get("endpoint_sources_json") or "").strip()
    if endpoint_sources_json:
        try:
            payload = json.loads(endpoint_sources_json)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            sources = []
            for source in payload:
                normalized_source = settings_service.normalize_endpoint_source_definition(source)
                if str(normalized_source.get("name") or "").strip():
                    sources.append(normalized_source)
            if sources:
                return sources

    names = form_data.getlist("endpoint_name")
    formats = form_data.getlist("endpoint_format")
    base_urls = form_data.getlist("endpoint_base_url")
    tokens = form_data.getlist("endpoint_token")
    template_ids = form_data.getlist("endpoint_api_template_id")
    organization_paths = form_data.getlist("endpoint_api_organizations_path")
    devices_paths = form_data.getlist("endpoint_api_devices_path")
    devices_org_params = form_data.getlist("endpoint_api_devices_org_param")
    latest_values_paths = form_data.getlist("endpoint_api_latest_values_path")
    latest_values_device_params = form_data.getlist("endpoint_api_latest_values_device_param")
    request_headers = form_data.getlist("endpoint_api_request_headers")
    token_urls = form_data.getlist("endpoint_api_token_url")
    token_methods = form_data.getlist("endpoint_api_token_method")
    token_fields = form_data.getlist("endpoint_api_token_field")
    auth_usernames = form_data.getlist("endpoint_api_auth_username")
    auth_passwords = form_data.getlist("endpoint_api_auth_password")
    auth_headers = form_data.getlist("endpoint_api_auth_headers")
    auth_bodies = form_data.getlist("endpoint_api_auth_body")
    mqtt_hosts = form_data.getlist("endpoint_mqtt_host")
    mqtt_ports = form_data.getlist("endpoint_mqtt_port")
    mqtt_usernames = form_data.getlist("endpoint_mqtt_username")
    mqtt_passwords = form_data.getlist("endpoint_mqtt_password")
    mqtt_topics = form_data.getlist("endpoint_mqtt_topic")

    max_len = max(
        len(names),
        len(formats),
        len(base_urls),
        len(tokens),
        len(template_ids),
        len(organization_paths),
        len(devices_paths),
        len(devices_org_params),
        len(latest_values_paths),
        len(latest_values_device_params),
        len(request_headers),
        len(token_urls),
        len(token_methods),
        len(token_fields),
        len(auth_usernames),
        len(auth_passwords),
        len(auth_headers),
        len(auth_bodies),
        len(mqtt_hosts),
        len(mqtt_ports),
        len(mqtt_usernames),
        len(mqtt_passwords),
        len(mqtt_topics),
        1,
    )
    sources = []
    for index in range(max_len):
        name = (names[index] if index < len(names) else "").strip()
        source_format = (formats[index] if index < len(formats) else "api").strip().lower()
        if source_format not in ("api", "mqtt"):
            source_format = "api"
        base_url = (base_urls[index] if index < len(base_urls) else "").strip().rstrip("/")
        token = (tokens[index] if index < len(tokens) else "").strip()
        template_id = (template_ids[index] if index < len(template_ids) else "").strip()
        organizations_path = (
            organization_paths[index] if index < len(organization_paths) else ""
        ).strip()
        devices_path = (devices_paths[index] if index < len(devices_paths) else "").strip()
        devices_org_param = (
            devices_org_params[index] if index < len(devices_org_params) else ""
        ).strip()
        latest_values_path = (
            latest_values_paths[index] if index < len(latest_values_paths) else ""
        ).strip()
        latest_values_device_param = (
            latest_values_device_params[index]
            if index < len(latest_values_device_params)
            else ""
        ).strip()
        request_headers_value = (
            request_headers[index] if index < len(request_headers) else "{}"
        ).strip()
        token_url = (token_urls[index] if index < len(token_urls) else "").strip()
        token_method = (token_methods[index] if index < len(token_methods) else "POST").strip()
        token_field = (token_fields[index] if index < len(token_fields) else "access_token").strip()
        auth_username = (
            auth_usernames[index] if index < len(auth_usernames) else ""
        ).strip()
        auth_password = (
            auth_passwords[index] if index < len(auth_passwords) else ""
        ).strip()
        auth_headers_value = (
            auth_headers[index] if index < len(auth_headers) else "{}"
        ).strip()
        auth_body = (auth_bodies[index] if index < len(auth_bodies) else "").strip()
        mqtt_host = (mqtt_hosts[index] if index < len(mqtt_hosts) else "").strip()
        mqtt_port_raw = (mqtt_ports[index] if index < len(mqtt_ports) else "1883").strip()
        mqtt_username = (mqtt_usernames[index] if index < len(mqtt_usernames) else "").strip()
        mqtt_password = (mqtt_passwords[index] if index < len(mqtt_passwords) else "").strip()
        mqtt_topic = (mqtt_topics[index] if index < len(mqtt_topics) else "").strip()
        if not name:
            continue
        try:
            mqtt_port = int(mqtt_port_raw or 1883)
        except ValueError:
            mqtt_port = 1883
        sources.append(
            {
                "name": name,
                "format": source_format,
                "base_url": base_url,
                "token": token,
                "api": {
                    "template_id": template_id,
                    "organizations_path": organizations_path,
                    "devices_path": devices_path,
                    "devices_org_param": devices_org_param,
                    "latest_values_path": latest_values_path,
                    "latest_values_device_param": latest_values_device_param,
                    "request_headers": request_headers_value or "{}",
                    "token_url": token_url,
                    "token_method": token_method or "POST",
                    "token_field": token_field or "access_token",
                    "auth_username": auth_username,
                    "auth_password": auth_password,
                    "auth_headers": auth_headers_value or "{}",
                    "auth_body": auth_body,
                },
                "mqtt": {
                    "host": mqtt_host,
                    "port": mqtt_port,
                    "username": mqtt_username,
                    "password": mqtt_password,
                    "topic": mqtt_topic,
                },
            }
        )

    if not sources:
        sources.append(settings_service.normalize_endpoint_source_definition({}))
    return sources


def _resolve_endpoint_source(source):
    return settings_service.normalize_endpoint_source_definition(source or {})


def _source_api_config(source):
    return _resolve_endpoint_source(source).get("api", {})


def _render_template_placeholders(value, variables):
    if not isinstance(value, str) or "{{" not in value:
        return value

    def replace(match):
        key = match.group(1).strip()
        return str(variables.get(key, match.group(0)))

    return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", replace, value)


def _parse_json_object(raw_value, label):
    if isinstance(raw_value, dict):
        return {
            str(key).strip(): str(value)
            for key, value in raw_value.items()
            if str(key).strip()
        }

    text = str(raw_value or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid {label}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {label}: expected a JSON object")
    return {str(key).strip(): str(item) for key, item in value.items() if str(key).strip()}


def _extract_json_path(payload, dotted_path):
    current = payload
    for segment in str(dotted_path or "").split("."):
        key = segment.strip()
        if not key:
            continue
        if isinstance(current, dict):
            if key not in current:
                return ""
            current = current[key]
            continue
        if isinstance(current, list) and key.isdigit():
            index = int(key)
            if index >= len(current):
                return ""
            current = current[index]
            continue
        return ""
    return current


def _source_api_requests(source):
    api_config = _source_api_config(source)
    requests = api_config.get("requests")
    if not isinstance(requests, list):
        return []
    return [request for request in requests if isinstance(request, dict)]


def _source_api_request(source, role):
    normalized_role = str(role or "").strip().lower()
    for request_definition in _source_api_requests(source):
        request_role = str(request_definition.get("role") or "").strip().lower()
        if request_role == normalized_role and str(request_definition.get("path") or "").strip():
            return request_definition
    return None


def _render_dynamic_value(value, context):
    if not isinstance(value, str):
        return value

    full_match = re.fullmatch(r"\{\{\s*([^{}]+?)\s*\}\}", value.strip())
    if full_match:
        return _extract_json_path(context, full_match.group(1).strip())

    def replace(match):
        resolved = _extract_json_path(context, match.group(1).strip())
        if resolved == "":
            return ""
        return str(resolved)

    return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", replace, value)


def _render_dynamic_text(value, context):
    rendered = _render_dynamic_value(value, context)
    if rendered in (None, ""):
        return ""
    if isinstance(rendered, (dict, list)):
        return json.dumps(rendered)
    return str(rendered)


def _append_query_value(target, key, value):
    if key not in target:
        target[key] = value
        return
    existing = target[key]
    if isinstance(existing, list):
        if isinstance(value, list):
            existing.extend(value)
        else:
            existing.append(value)
        return
    target[key] = [existing]
    if isinstance(value, list):
        target[key].extend(value)
    else:
        target[key].append(value)


def _render_request_query(request_definition, context):
    query = {}
    params = request_definition.get("params")
    if not isinstance(params, list):
        return query

    for item in params:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        raw_values = item.get("values")
        if isinstance(raw_values, list):
            candidate_values = raw_values
        elif raw_values not in (None, ""):
            candidate_values = [raw_values]
        else:
            candidate_values = [item.get("value") or ""]
        for raw_value in candidate_values:
            raw_text = str(raw_value or "")
            rendered_value = _render_dynamic_value(raw_text, context)
            if rendered_value == "" and raw_text.strip().startswith("{{"):
                continue
            _append_query_value(query, key, rendered_value if rendered_value != "" else "")
    return query


def _build_source_request_context(source, organizations=None, devices=None):
    organization_items = _coerce_collection_items(organizations)
    device_items = _coerce_collection_items(devices)
    first_organization = organization_items[0] if organization_items else {}
    first_device = device_items[0] if device_items else {}
    device_uuids = [
        item.get("uuid") or item.get("device_uuid") or item.get("id") or item.get("device_id")
        for item in device_items
        if isinstance(item, dict)
    ]
    device_uuids = [str(item).strip() for item in device_uuids if str(item).strip()]

    return {
        "source_name": str(source.get("name") or "").strip(),
        "base_url": str(source.get("base_url") or "").strip(),
        "organization": first_organization if isinstance(first_organization, dict) else {},
        "organizations": organization_items,
        "organization_uuid": (
            str(
                (first_organization or {}).get("uuid")
                or (first_organization or {}).get("org_uuid")
                or (first_organization or {}).get("id")
                or ""
            ).strip()
            if isinstance(first_organization, dict)
            else ""
        ),
        "device": first_device if isinstance(first_device, dict) else {},
        "devices": device_items,
        "device_uuid": (
            str(
                (first_device or {}).get("uuid")
                or (first_device or {}).get("device_uuid")
                or (first_device or {}).get("id")
                or (first_device or {}).get("device_id")
                or ""
            ).strip()
            if isinstance(first_device, dict)
            else ""
        ),
        "device_uuids": device_uuids,
    }


def _source_device_uuid(device):
    if not isinstance(device, dict):
        return ""
    return str(
        device.get("uuid")
        or device.get("device_uuid")
        or device.get("id")
        or device.get("device_id")
        or ""
    ).strip()


def _source_device_display_name(device):
    if not isinstance(device, dict):
        return ""
    return str(
        device.get("display_name")
        or device.get("name")
        or device.get("device_name")
        or device.get("label")
        or device.get("uuid")
        or device.get("device_uuid")
        or device.get("device_id")
        or device.get("id")
        or ""
    ).strip()


def _has_latest_value_payload(payload):
    if isinstance(payload, list):
        return len(payload) > 0
    if isinstance(payload, dict):
        items = _coerce_collection_items(payload)
        if items:
            return True
        return any(value not in (None, "", [], {}) for value in payload.values())
    return payload not in (None, "")


def _normalize_source_preview_execution_state(execution_state):
    state = execution_state if isinstance(execution_state, dict) else {}
    request_counts = state.get("request_counts")
    normalized_counts = {}
    if isinstance(request_counts, dict):
        for key, value in request_counts.items():
            request_key = str(key or "").strip()
            if not request_key:
                continue
            try:
                normalized_counts[request_key] = max(0, int(value or 0))
            except (TypeError, ValueError):
                continue
    return {
        "request_counts": normalized_counts,
        "organizations": state.get("organizations") if isinstance(state.get("organizations"), (list, dict)) else [],
        "devices": state.get("devices") if isinstance(state.get("devices"), (list, dict)) else [],
        "latest_values": (
            state.get("latest_values")
            if isinstance(state.get("latest_values"), (list, dict))
            else {"items": []}
        ),
    }


def _source_request_execution_key(request_definition):
    normalized_request = settings_service.normalize_endpoint_api_request_definition(
        request_definition,
        0,
    )
    return str(
        normalized_request.get("id")
        or normalized_request.get("role")
        or normalized_request.get("name")
        or normalized_request.get("path")
        or "request"
    ).strip()


def _should_execute_source_request(request_definition, execution_state):
    normalized_request = settings_service.normalize_endpoint_api_request_definition(
        request_definition,
        0,
    )
    if normalized_request.get("interval_unlimited"):
        return True

    try:
        max_round_times = int(
            normalized_request.get("max_round_times")
            or normalized_request.get("max_interval_minutes")
            or 0
        )
    except (TypeError, ValueError):
        max_round_times = 0

    if max_round_times <= 0:
        return False

    request_counts = execution_state.get("request_counts", {})
    executed_count = request_counts.get(_source_request_execution_key(normalized_request), 0)
    return executed_count < max_round_times


def _increment_source_request_execution_count(execution_state, request_definition):
    request_key = _source_request_execution_key(request_definition)
    if not request_key:
        return
    request_counts = execution_state.setdefault("request_counts", {})
    request_counts[request_key] = int(request_counts.get(request_key, 0) or 0) + 1


def _latest_value_item_device_uuid(item):
    if not isinstance(item, dict):
        return ""
    nested_device = item.get("device")
    nested_device_uuid = _source_device_uuid(nested_device) if isinstance(nested_device, dict) else ""
    return str(
        item.get("device_uuid")
        or item.get("uuid")
        or item.get("device_id")
        or item.get("id")
        or nested_device_uuid
        or ""
    ).strip()


def _coerce_latest_value_items(payload):
    items = _coerce_collection_items(payload)
    if items:
        return [item for item in items if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _map_latest_values_to_devices(payload, devices):
    latest_items = _coerce_latest_value_items(payload)
    device_items = _coerce_collection_items(devices)
    latest_value_map = {}

    for item in latest_items:
        device_uuid = _latest_value_item_device_uuid(item)
        if device_uuid and device_uuid not in latest_value_map:
            latest_value_map[device_uuid] = item

    if latest_value_map:
        return latest_value_map

    if len(latest_items) == len(device_items):
        for index, device in enumerate(device_items):
            device_uuid = _source_device_uuid(device)
            if device_uuid and index < len(latest_items):
                latest_value_map[device_uuid] = latest_items[index]
        if latest_value_map:
            return latest_value_map

    if len(device_items) == 1 and _has_latest_value_payload(payload):
        device_uuid = _source_device_uuid(device_items[0])
        if device_uuid:
            latest_value_map[device_uuid] = payload

    return latest_value_map


def _build_ready_source_devices(device_items, payload):
    latest_value_map = _map_latest_values_to_devices(payload, device_items)
    ready_devices = []
    for device in device_items:
        device_uuid = _source_device_uuid(device)
        if not device_uuid:
            continue
        device_payload = latest_value_map.get(device_uuid)
        if not _has_latest_value_payload(device_payload):
            continue
        device_entry = dict(device)
        device_entry["display_name"] = _source_device_display_name(device_entry) or device_uuid
        device_entry["latest_values"] = device_payload
        ready_devices.append(device_entry)
    return ready_devices, latest_value_map


def _load_ready_source_devices(settings, source, organizations, devices):
    latest_values_request = _source_api_request(source, "latest_values")
    device_items = _coerce_collection_items(devices)
    if not latest_values_request or not device_items:
        return [], {}, {"items": []}, source, False

    current_source = source
    settings_updated = False
    try:
        payload, current_source, request_updated = _execute_source_request(
            settings,
            current_source,
            latest_values_request,
            _build_source_request_context(current_source, organizations=organizations, devices=device_items),
        )
        settings_updated = settings_updated or request_updated
    except Exception:
        return [], {}, {"items": []}, current_source, settings_updated

    if not _has_latest_value_payload(payload):
        return [], {}, {"items": []}, current_source, settings_updated

    ready_devices, latest_value_map = _build_ready_source_devices(device_items, payload)
    latest_values_payload = payload if isinstance(payload, dict) else {"items": _coerce_collection_items(payload)}
    return ready_devices, latest_value_map, latest_values_payload, current_source, settings_updated


def _sync_latest_values_payload_to_sensor_data(settings, source, payload):
    normalized_payload = payload if isinstance(payload, dict) else {"items": _coerce_collection_items(payload)}
    if not _has_latest_value_payload(normalized_payload):
        return False, {"inserted": 0, "matched_devices": 0}

    settings_updated = data_service.sync_source_metric_fields(
        settings,
        source.get("name"),
        normalized_payload,
    )
    try:
        ingest_result = data_service.ingest_source_latest_values_payload(
            normalized_payload,
            source_name=source.get("name"),
        )
    except Exception:
        ingest_result = {"inserted": 0, "matched_devices": 0}
    return settings_updated, ingest_result


def _merge_query_params(url, query):
    if not query:
        return url

    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    for key, value in query.items():
        if isinstance(value, (list, tuple)):
            query_items.extend((key, item) for item in value)
        else:
            query_items.append((key, value))
    return parsed._replace(query=urlencode(query_items, doseq=True)).geturl()


def _resolve_request_url(source, path_or_url):
    path_value = str(path_or_url or "").strip()
    if not path_value:
        raise ValueError("Request URL is required")
    if path_value.lower().startswith(("http://", "https://")):
        return path_value

    base_url = str(source.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("Base URL is required")
    if path_value.startswith("/"):
        return f"{base_url}{path_value}"
    return f"{base_url}/{path_value}"


def _request_json(url, method="GET", headers=None, body=None):
    request_headers = headers or {}
    request_body = body
    if isinstance(request_body, str):
        request_body = request_body.encode("utf-8")
    request_obj = Request(url, headers=request_headers, method=method.upper(), data=request_body)
    with urlopen(request_obj, timeout=15) as response:
        payload = response.read().decode("utf-8")
    if not payload.strip():
        return {}
    return json.loads(payload)


def _coerce_collection_items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "rows", "devices", "organizations", "values"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _normalize_history_json_value(value):
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return {}
    return {"value": value}


def _request_debug_payload(request_definition, method, request_path, url, request_query, request_headers, body_text):
    return {
        "method": method,
        "path": request_path,
        "url": url,
        "query": request_query,
        "headers": request_headers,
        "body": body_text,
        "use_auth": bool(request_definition.get("use_auth", True)),
        "role": str(request_definition.get("role") or "").strip().lower(),
        "name": str(request_definition.get("name") or "").strip(),
    }


def _record_source_request_history(source, request_debug, *, response_payload=None, response_status="", response_code=None, error_message=""):
    log_api_request_history(
        {
            "source_name": str(source.get("name") or "").strip(),
            "request_role": str(request_debug.get("role") or "").strip(),
            "request_name": str(request_debug.get("name") or "").strip(),
            "request_method": str(request_debug.get("method") or "").strip(),
            "request_path": str(request_debug.get("path") or "").strip(),
            "request_url": str(request_debug.get("url") or "").strip(),
            "use_auth": bool(request_debug.get("use_auth", True)),
            "request_headers": _normalize_history_json_value(request_debug.get("headers")),
            "request_query": _normalize_history_json_value(request_debug.get("query")),
            "request_body": str(request_debug.get("body") or ""),
            "response_status": response_status,
            "response_code": response_code,
            "response_payload": _normalize_history_json_value(response_payload),
            "error_message": str(error_message or "").strip(),
        }
    )


def _http_error_payload(exc):
    status_code = getattr(exc, "code", None)
    response_text = ""
    try:
        response_text = exc.read().decode("utf-8")
    except Exception:
        response_text = ""

    if not response_text.strip():
        return status_code, {"error": str(exc)}

    try:
        return status_code, json.loads(response_text)
    except json.JSONDecodeError:
        return status_code, {"raw": response_text}


def _apply_source_request_auth(
    settings,
    source,
    request_definition,
    headers,
    query,
    force_token_refresh=False,
):
    request_source = _resolve_endpoint_source(source)
    request_headers = dict(headers)
    request_query = dict(query)
    auth_updated = False

    if not request_definition.get("use_auth", True):
        return request_source, request_headers, request_query, auth_updated

    api_config = request_source.get("api", {})
    auth_type = str(api_config.get("auth_type") or "none").strip().lower()
    if auth_type == "none":
        return request_source, request_headers, request_query, auth_updated

    if auth_type == "bearer_token":
        token = str(request_source.get("token") or "").strip()
        if not token:
            raise ValueError("Bearer token is required for this source")
        request_headers["Authorization"] = f"Bearer {token}"
        return request_source, request_headers, request_query, auth_updated

    if auth_type == "bearer_login":
        if force_token_refresh:
            request_source["token"] = ""
        token = str(request_source.get("token") or "").strip()
        if not token:
            token = _fetch_source_token(request_source)
            request_source["token"] = token
            auth_updated = _save_shared_source_token(settings, request_source, token) or auth_updated
        request_headers["Authorization"] = f"Bearer {token}"
        return request_source, request_headers, request_query, auth_updated

    if auth_type == "basic":
        username = str(api_config.get("auth_username") or "").strip()
        password = str(api_config.get("auth_password") or "")
        credentials = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        request_headers["Authorization"] = f"Basic {credentials}"
        return request_source, request_headers, request_query, auth_updated

    if auth_type == "api_key_header":
        api_key_name = str(api_config.get("api_key_name") or "").strip()
        api_key_value = str(api_config.get("api_key_value") or "").strip()
        if not api_key_name or not api_key_value:
            raise ValueError("API key name and value are required")
        request_headers[api_key_name] = api_key_value
        return request_source, request_headers, request_query, auth_updated

    if auth_type == "api_key_query":
        api_key_name = str(api_config.get("api_key_name") or "").strip()
        api_key_value = str(api_config.get("api_key_value") or "").strip()
        if not api_key_name or not api_key_value:
            raise ValueError("API key name and value are required")
        _append_query_value(request_query, api_key_name, api_key_value)
        return request_source, request_headers, request_query, auth_updated

    if auth_type == "custom_headers":
        request_headers.update(
            _parse_json_object(api_config.get("custom_auth_headers"), "custom auth headers")
        )
        return request_source, request_headers, request_query, auth_updated

    return request_source, request_headers, request_query, auth_updated


def _execute_source_request(settings, source, request_definition, context=None, include_request_debug=False):
    normalized_source = _resolve_endpoint_source(source)
    api_config = normalized_source.get("api", {})
    request_context = context or {}
    auth_type = str(api_config.get("auth_type") or "none").strip().lower()
    use_auth = bool(request_definition.get("use_auth", True))
    method = str(request_definition.get("method") or "GET").strip().upper() or "GET"
    request_path = str(request_definition.get("path") or "").strip()
    if not request_path:
        raise ValueError("Request path is required")

    def perform(force_token_refresh=False):
        headers = {"Accept": "application/json"}
        headers.update(_parse_json_object(api_config.get("request_headers"), "request headers"))
        query = _render_request_query(request_definition, request_context)
        request_source, request_headers, request_query, auth_updated = _apply_source_request_auth(
            settings,
            normalized_source,
            request_definition,
            headers,
            query,
            force_token_refresh=force_token_refresh,
        )
        body_text = _render_dynamic_text(request_definition.get("body") or "", request_context).strip()
        body = body_text if method not in {"GET", "DELETE"} and body_text else None
        url = _resolve_request_url(request_source, request_path)
        url = _merge_query_params(url, request_query)
        request_debug = _request_debug_payload(
            request_definition,
            method,
            request_path,
            url,
            request_query,
            request_headers,
            body_text,
        )
        try:
            payload = _request_json(url, method=method, headers=request_headers, body=body)
        except HTTPError as exc:
            response_code, error_payload = _http_error_payload(exc)
            _record_source_request_history(
                request_source,
                request_debug,
                response_payload=error_payload,
                response_status="error",
                response_code=response_code,
                error_message=str(exc),
            )
            raise
        except URLError as exc:
            _record_source_request_history(
                request_source,
                request_debug,
                response_payload={"error": str(exc)},
                response_status="error",
                error_message=str(exc),
            )
            raise
        except Exception as exc:
            _record_source_request_history(
                request_source,
                request_debug,
                response_payload={"error": str(exc)},
                response_status="error",
                error_message=str(exc),
            )
            raise
        _record_source_request_history(
            request_source,
            request_debug,
            response_payload=payload,
            response_status="success",
            response_code=200,
        )
        role = str(request_definition.get("role") or "").strip().lower()
        if role == "latest_values":
            sync_updated, ingest_result = _sync_latest_values_payload_to_sensor_data(
                settings,
                request_source,
                payload,
            )
            auth_updated = auth_updated or sync_updated
            request_source["_latest_values_ingest_result"] = ingest_result
            request_source["_latest_values_settings_updated"] = bool(sync_updated)
        if include_request_debug:
            return (
                payload,
                request_source,
                auth_updated,
                request_debug,
            )
        return payload, request_source, auth_updated

    def request_label():
        request_name = str(request_definition.get("name") or "").strip()
        request_role = str(request_definition.get("role") or "").strip().lower()
        request_path_label = str(request_definition.get("path") or "").strip()
        return request_name or request_role or request_path_label or "request"

    try:
        return perform(False)
    except Exception as exc:
        if auth_type == "bearer_login" and use_auth:
            try:
                return perform(True)
            except Exception as retry_exc:
                raise ValueError(
                    f"{request_label()} failed: {retry_exc}"
                ) from retry_exc
        raise ValueError(f"{request_label()} failed: {exc}") from exc


def _load_source_request_test_data(settings, source, request_definition):
    normalized_source = _resolve_endpoint_source(source)
    normalized_request = settings_service.normalize_endpoint_api_request_definition(
        request_definition,
        0,
    )
    target_role = str(normalized_request.get("role") or "").strip().lower()
    organizations_request = _source_api_request(normalized_source, "organizations")
    devices_request = _source_api_request(normalized_source, "devices")

    organizations = []
    devices = []
    settings_updated = False

    should_load_organizations = target_role in {"devices", "latest_values", "custom"}
    should_load_devices = target_role in {"latest_values", "custom"}

    if should_load_organizations and organizations_request:
        organizations, normalized_source, request_updated = _execute_source_request(
            settings,
            normalized_source,
            organizations_request,
            _build_source_request_context(normalized_source),
        )
        settings_updated = settings_updated or request_updated

    if should_load_devices and devices_request:
        devices, normalized_source, request_updated = _execute_source_request(
            settings,
            normalized_source,
            devices_request,
            _build_source_request_context(normalized_source, organizations=organizations),
        )
        settings_updated = settings_updated or request_updated

    payload, normalized_source, request_updated, request_debug = _execute_source_request(
        settings,
        normalized_source,
        normalized_request,
        _build_source_request_context(
            normalized_source,
            organizations=organizations,
            devices=devices,
        ),
        include_request_debug=True,
    )
    settings_updated = settings_updated or request_updated

    return {
        "source": normalized_source,
        "request": request_debug,
        "payload": payload,
        "organizations": organizations,
        "organization_items": _coerce_collection_items(organizations),
        "devices": devices,
        "device_items": _coerce_collection_items(devices),
        "settings_updated": settings_updated,
        "cache_key": _get_source_cache_key(normalized_source),
    }


def _load_source_preview_data(settings, source, execution_state=None):
    normalized_source = _resolve_endpoint_source(source)
    organizations_request = _source_api_request(normalized_source, "organizations")
    devices_request = _source_api_request(normalized_source, "devices")
    latest_values_request = _source_api_request(normalized_source, "latest_values")
    execution_state = _normalize_source_preview_execution_state(execution_state)

    if not organizations_request:
        raise ValueError("Organizations request is required")
    if not devices_request:
        raise ValueError("Devices request is required")

    settings_updated = False
    organizations = execution_state.get("organizations", [])
    if _should_execute_source_request(organizations_request, execution_state) or not _coerce_collection_items(organizations):
        organizations, normalized_source, request_updated = _execute_source_request(
            settings,
            normalized_source,
            organizations_request,
            _build_source_request_context(normalized_source),
        )
        settings_updated = settings_updated or request_updated
        _increment_source_request_execution_count(execution_state, organizations_request)

    devices = execution_state.get("devices", [])
    if _should_execute_source_request(devices_request, execution_state) or not _coerce_collection_items(devices):
        devices, normalized_source, request_updated = _execute_source_request(
            settings,
            normalized_source,
            devices_request,
            _build_source_request_context(normalized_source, organizations=organizations),
        )
        settings_updated = settings_updated or request_updated
        _increment_source_request_execution_count(execution_state, devices_request)

    latest_values = execution_state.get("latest_values", {"items": []})
    ready_device_items = []
    latest_value_map = {}
    if latest_values_request:
        if _should_execute_source_request(latest_values_request, execution_state) or not _has_latest_value_payload(latest_values):
            (
                ready_device_items,
                latest_value_map,
                latest_values,
                normalized_source,
                request_updated,
            ) = _load_ready_source_devices(
                settings,
                normalized_source,
                organizations,
                devices,
            )
            settings_updated = settings_updated or request_updated
            _increment_source_request_execution_count(execution_state, latest_values_request)
        else:
            ready_device_items, latest_value_map = _build_ready_source_devices(
                _coerce_collection_items(devices),
                latest_values,
            )

    execution_state["organizations"] = organizations
    execution_state["devices"] = devices
    execution_state["latest_values"] = latest_values

    return {
        "source": normalized_source,
        "organizations": organizations,
        "organization_items": _coerce_collection_items(organizations),
        "devices": devices,
        "device_items": _coerce_collection_items(devices),
        "ready_device_items": ready_device_items,
        "latest_value_map": latest_value_map,
        "latest_values": latest_values,
        "execution_state": execution_state,
        "settings_updated": settings_updated,
        "cache_key": _get_source_cache_key(normalized_source),
    }


def _get_source_cache_key(source):
    normalized_source = _resolve_endpoint_source(source)
    api_config = normalized_source.get("api", {})
    candidates = [api_config.get("token_url"), normalized_source.get("base_url")]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value:
            continue
        parsed = urlparse(value if "://" in value else f"//{value}")
        host = (parsed.netloc or parsed.path.split("/")[0]).strip().lower()
        if host:
            return host
    return ""


def _apply_cached_source_token(settings, source):
    cache_key = _get_source_cache_key(source)
    if not cache_key or str(source.get("token") or "").strip():
        return False

    token_store = settings.get("endpoint_token_store", {})
    cached_token = str((token_store.get(cache_key) or {}).get("token") or "").strip()
    if not cached_token:
        return False

    source["token"] = cached_token
    return True


def _sync_endpoint_token_store(settings):
    token_store = settings.get("endpoint_token_store", {})
    normalized_store = {}
    updated = False

    for source in settings.get("endpoint_sources", []):
        cache_key = _get_source_cache_key(source)
        if not cache_key:
            continue

        existing_entry = normalized_store.get(cache_key) or token_store.get(cache_key) or {}
        source_token = str(source.get("token") or "").strip()
        cached_token = str(existing_entry.get("token") or "").strip()
        effective_token = source_token or cached_token
        source_name = str(source.get("name") or "").strip()
        existing_names = existing_entry.get("source_names")
        source_names = set(existing_names if isinstance(existing_names, list) else [])
        if source_name:
            source_names.add(source_name)

        if effective_token and source_token != effective_token:
            source["token"] = effective_token
            updated = True

        entry = {}
        if effective_token:
            entry["token"] = effective_token
            entry["updated_at"] = str(existing_entry.get("updated_at") or datetime.now(timezone.utc).isoformat())
        if source_names:
            entry["source_names"] = sorted(source_names)
        normalized_store[cache_key] = entry

    if normalized_store != token_store:
        settings["endpoint_token_store"] = normalized_store
        updated = True
    return updated


def _save_shared_source_token(settings, source, token):
    cache_key = _get_source_cache_key(source)
    updated = False
    normalized_token = str(token or "").strip()
    if not normalized_token:
        return updated

    if cache_key:
        for candidate in settings.get("endpoint_sources", []):
            if _get_source_cache_key(candidate) == cache_key and candidate.get("token") != normalized_token:
                candidate["token"] = normalized_token
                updated = True

        token_store = settings.setdefault("endpoint_token_store", {})
        existing_entry = token_store.get(cache_key) or {}
        source_names = set(existing_entry.get("source_names") or [])
        source_name = str(source.get("name") or "").strip()
        if source_name:
            source_names.add(source_name)
        new_entry = {
            "token": normalized_token,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source_names": sorted(name for name in source_names if name),
        }
        if token_store.get(cache_key) != new_entry:
            token_store[cache_key] = new_entry
            updated = True

    return _sync_endpoint_token_store(settings) or updated


def _normalize_endpoint_source_list(sources):
    normalized_sources = []
    if isinstance(sources, list):
        for source in sources:
            normalized_source = _resolve_endpoint_source(source)
            if str(normalized_source.get("name") or "").strip():
                normalized_sources.append(normalized_source)
    return normalized_sources or [settings_service.normalize_endpoint_source_definition({})]


def _background_source_polling_enabled():
    return _env_flag("ICON_ENABLE_BACKGROUND_POLLING", default=True)


def _background_source_polling_process_ready():
    if not _background_source_polling_enabled():
        return False
    if _env_flag("ICON_DEBUG", default=True) and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


def _background_source_polling_state_key(source):
    normalized_source = _resolve_endpoint_source(source)
    source_name = str(normalized_source.get("name") or "").strip()
    if source_name:
        return source_name
    return _get_source_cache_key(normalized_source) or uuid.uuid4().hex


def _background_source_polling_signature(source):
    normalized_source = _resolve_endpoint_source(source)
    return json.dumps(normalized_source, sort_keys=True, ensure_ascii=True)


def _latest_values_poll_interval_seconds(source):
    latest_values_request = _source_api_request(source, "latest_values")
    if not latest_values_request:
        return 0

    normalized_request = settings_service.normalize_endpoint_api_request_definition(
        latest_values_request,
        0,
    )
    if not normalized_request.get("interval_unlimited"):
        return 0

    try:
        interval_minutes = int(
            normalized_request.get("run_every_times")
            or normalized_request.get("run_interval_minutes")
            or 0
        )
    except (TypeError, ValueError):
        interval_minutes = 0
    return max(0, interval_minutes) * 60


def _prune_background_source_polling_state(active_source_keys):
    with _BACKGROUND_SOURCE_POLLING_STATE_LOCK:
        stale_keys = [
            key for key in list(_BACKGROUND_SOURCE_POLLING_STATE.keys()) if key not in active_source_keys
        ]
        for key in stale_keys:
            _BACKGROUND_SOURCE_POLLING_STATE.pop(key, None)


def _run_background_source_polling_cycle():
    settings = settings_service.load_settings()
    settings_updated = _sync_endpoint_token_store(settings)
    active_source_keys = set()
    now = time.time()

    for source in _normalize_endpoint_source_list(settings.get("endpoint_sources", [])):
        normalized_source = _resolve_endpoint_source(source)
        source_name = str(normalized_source.get("name") or "").strip()
        if normalized_source.get("format") != "api" or not source_name:
            continue

        interval_seconds = _latest_values_poll_interval_seconds(normalized_source)
        if interval_seconds <= 0:
            continue

        source_key = _background_source_polling_state_key(normalized_source)
        active_source_keys.add(source_key)
        source_signature = _background_source_polling_signature(normalized_source)
        with _BACKGROUND_SOURCE_POLLING_STATE_LOCK:
            state_entry = _BACKGROUND_SOURCE_POLLING_STATE.get(source_key)
            if not isinstance(state_entry, dict) or state_entry.get("signature") != source_signature:
                state_entry = {
                    "signature": source_signature,
                    "execution_state": {},
                    "next_run_at": 0.0,
                }
                _BACKGROUND_SOURCE_POLLING_STATE[source_key] = state_entry

            next_run_at = float(state_entry.get("next_run_at") or 0.0)
            execution_state = state_entry.get("execution_state") or {}

        if next_run_at > now:
            continue

        try:
            preview_payload = _load_source_preview_data(
                settings,
                normalized_source,
                execution_state,
            )
        except Exception as exc:
            with _BACKGROUND_SOURCE_POLLING_STATE_LOCK:
                if source_key in _BACKGROUND_SOURCE_POLLING_STATE:
                    _BACKGROUND_SOURCE_POLLING_STATE[source_key]["next_run_at"] = time.time() + interval_seconds
                    _BACKGROUND_SOURCE_POLLING_STATE[source_key]["last_error"] = str(exc)
                    _BACKGROUND_SOURCE_POLLING_STATE[source_key]["last_error_at"] = (
                        datetime.now(timezone.utc).isoformat()
                    )
            print(f"[background] Latest Values polling failed for '{source_name}': {exc}")
            continue

        settings_updated = settings_updated or bool(preview_payload.get("settings_updated", False))
        settings_updated = settings_updated or bool(
            preview_payload.get("source", {}).get("_latest_values_settings_updated", False)
        )
        with _BACKGROUND_SOURCE_POLLING_STATE_LOCK:
            if source_key in _BACKGROUND_SOURCE_POLLING_STATE:
                _BACKGROUND_SOURCE_POLLING_STATE[source_key].update(
                    {
                        "execution_state": preview_payload.get("execution_state", {}),
                        "next_run_at": time.time() + interval_seconds,
                        "last_success_at": datetime.now(timezone.utc).isoformat(),
                        "last_error": "",
                    }
                )

    _prune_background_source_polling_state(active_source_keys)
    if settings_updated:
        settings_service.save_settings(settings)


def _background_source_polling_loop():
    init_all()
    seed_demo_data()
    print("[background] Latest Values polling thread started.")
    while True:
        try:
            _run_background_source_polling_cycle()
        except Exception as exc:
            print(f"[background] Latest Values polling cycle crashed: {exc}")
        time.sleep(15)


def _ensure_background_source_polling_started():
    global _BACKGROUND_SOURCE_POLLING_THREAD

    if not _background_source_polling_process_ready():
        return

    with _BACKGROUND_SOURCE_POLLING_LOCK:
        if _BACKGROUND_SOURCE_POLLING_THREAD and _BACKGROUND_SOURCE_POLLING_THREAD.is_alive():
            return

        _BACKGROUND_SOURCE_POLLING_THREAD = threading.Thread(
            target=_background_source_polling_loop,
            name="icon-latest-values-poller",
            daemon=True,
        )
        _BACKGROUND_SOURCE_POLLING_THREAD.start()


def _fetch_source_token(source):
    normalized_source = _resolve_endpoint_source(source)
    api_config = normalized_source.get("api", {})
    token_url = str(api_config.get("token_url") or "").strip()
    if not token_url:
        raise ValueError("Token URL is required")

    method = str(api_config.get("token_method") or "POST").strip().upper()
    variables = {
        "username": str(api_config.get("auth_username") or ""),
        "password": str(api_config.get("auth_password") or ""),
        "base_url": str(normalized_source.get("base_url") or ""),
        "token": str(normalized_source.get("token") or ""),
    }
    headers_text = _render_template_placeholders(api_config.get("auth_headers") or "{}", variables)
    headers = _parse_json_object(headers_text, "auth headers")
    headers.setdefault("Accept", "application/json")

    body_text = _render_template_placeholders(api_config.get("auth_body") or "", variables).strip()
    if body_text and not any(str(key).lower() == "content-type" for key in headers):
        headers["Content-Type"] = (
            "application/json" if body_text.startswith(("{", "[")) else "application/x-www-form-urlencoded"
        )

    response_payload = _request_json(
        _resolve_request_url(normalized_source, token_url),
        method=method,
        headers=headers,
        body=body_text if method != "GET" and body_text else None,
    )

    token_field = str(api_config.get("token_field") or "access_token").strip()
    token = _extract_json_path(response_payload, token_field) if token_field else ""
    if not token and isinstance(response_payload, dict):
        for key in ("access_token", "token", "bearer_token", "bearerToken"):
            token = response_payload.get(key)
            if token:
                break

    normalized_token = str(token or "").strip()
    if not normalized_token:
        raise ValueError("Token response did not include a bearer token")
    return normalized_token


def _resolve_source_from_request(settings, default_name="", payload=None):
    payload = payload if payload is not None else (request.get_json(silent=True) or {})
    source_payload = payload.get("source")
    source_name = (
        payload.get("source_name") or request.args.get("source_name") or default_name or ""
    ).strip()

    if isinstance(source_payload, dict):
        source = _resolve_endpoint_source(source_payload)
        if source_name and not str(source.get("name") or "").strip():
            source["name"] = source_name
    else:
        if not source_name:
            raise ValueError("Missing source_name")
        source = _find_source_by_name(settings, source_name)
        if not source:
            raise LookupError(f"Source '{source_name}' not found")
        source = _resolve_endpoint_source(source)

    if not str(source.get("name") or "").strip():
        source["name"] = source_name or "LIV-24 IAQ"
    _apply_cached_source_token(settings, source)
    return source


def _find_source_by_name(settings, source_name):
    sources = settings.get("endpoint_sources", [])
    for source in sources:
        if source.get("name") == source_name:
            return source
    return None


def _source_request_history_filters(source, request_definition):
    normalized_request = settings_service.normalize_endpoint_api_request_definition(
        request_definition,
        0,
    )
    return {
        "source_name": str(source.get("name") or "").strip(),
        "request_role": str(normalized_request.get("role") or "").strip().lower(),
        "request_name": str(normalized_request.get("name") or "").strip(),
        "request_method": str(normalized_request.get("method") or "").strip().upper(),
        "request_path": str(normalized_request.get("path") or "").strip(),
    }


def _history_date_range_filters(start_date_text="", end_date_text=""):
    filters = {}
    start_date_text = str(start_date_text or "").strip()
    end_date_text = str(end_date_text or "").strip()

    if start_date_text:
        start_date = datetime.strptime(start_date_text, "%Y-%m-%d").date()
        filters["created_from"] = datetime.combine(
            start_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        ).isoformat()

    if end_date_text:
        end_date = datetime.strptime(end_date_text, "%Y-%m-%d").date() + timedelta(days=1)
        filters["created_to"] = datetime.combine(
            end_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        ).isoformat()

    return filters


def _normalize_history_date_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Invalid date format")


def _source_request_history_owner_key():
    user_id = session.get("user_id")
    username = session.get("username")
    return f"{user_id}:{username}"


def _build_source_request_history_filename(source_name, start_date="", end_date=""):
    filename_parts = ["source_request_history", str(source_name or "").strip().replace(" ", "_")]
    if start_date:
        filename_parts.append(str(start_date).strip())
    if end_date:
        filename_parts.append(str(end_date).strip())
    return "_".join(part for part in filename_parts if part) + ".csv"


def _write_source_request_history_csv(file_obj, rows):
    writer = csv.writer(file_obj)
    writer.writerow(
        [
            "id",
            "created_at",
            "source_name",
            "request_role",
            "request_name",
            "request_method",
            "request_path",
            "request_url",
            "use_auth",
            "request_headers",
            "request_query",
            "request_body",
            "response_status",
            "response_code",
            "response_payload",
            "error_message",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get("id"),
                row.get("created_at"),
                row.get("source_name"),
                row.get("request_role"),
                row.get("request_name"),
                row.get("request_method"),
                row.get("request_path"),
                row.get("request_url"),
                1 if row.get("use_auth") else 0,
                json.dumps(row.get("request_headers") or {}, ensure_ascii=False),
                json.dumps(row.get("request_query") or {}, ensure_ascii=False),
                row.get("request_body") or "",
                row.get("response_status") or "",
                row.get("response_code"),
                json.dumps(row.get("response_payload") or {}, ensure_ascii=False),
                row.get("error_message") or "",
            ]
        )


def _remove_source_request_history_export_file(file_path):
    path = str(file_path or "").strip()
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _parse_source_request_history_job_datetime(value):
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)


def _prune_source_request_history_jobs():
    stale_jobs = []
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_SOURCE_REQUEST_HISTORY_JOB_RETENTION_SECONDS)
    with _SOURCE_REQUEST_HISTORY_JOB_LOCK:
        for job_id in list(_SOURCE_REQUEST_HISTORY_JOBS.keys()):
            job = _SOURCE_REQUEST_HISTORY_JOBS[job_id]
            updated_at = _parse_source_request_history_job_datetime(job.get("updated_at"))
            if updated_at >= cutoff:
                continue
            stale_jobs.append(_SOURCE_REQUEST_HISTORY_JOBS.pop(job_id))
    for job in stale_jobs:
        _remove_source_request_history_export_file(job.get("file_path"))


def _update_source_request_history_job(job_id, **changes):
    with _SOURCE_REQUEST_HISTORY_JOB_LOCK:
        job = _SOURCE_REQUEST_HISTORY_JOBS.get(job_id)
        if not job:
            return None
        job.update(changes)
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        return dict(job)


def _serialize_source_request_history_job(job):
    payload = {
        "job_id": job.get("job_id"),
        "mode": job.get("mode"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "row_count": int(job.get("row_count") or 0),
    }
    if job.get("error"):
        payload["error"] = job.get("error")
    if job.get("mode") == "list" and job.get("status") == "completed":
        payload["history"] = job.get("history") or []
    if job.get("mode") == "export" and job.get("status") == "completed":
        payload["download_name"] = job.get("download_name") or ""
        if job.get("file_path"):
            payload["download_url"] = url_for(
                "download_endpoint_source_request_history_job",
                job_id=job.get("job_id"),
            )
    return payload


def _get_source_request_history_job_for_current_user(job_id):
    _prune_source_request_history_jobs()
    owner_key = _source_request_history_owner_key()
    with _SOURCE_REQUEST_HISTORY_JOB_LOCK:
        job = _SOURCE_REQUEST_HISTORY_JOBS.get(job_id)
        if not job:
            return None
        if job.get("owner_key") != owner_key:
            return None
        return dict(job)


def _run_source_request_history_job(
    job_id,
    *,
    mode,
    history_filters,
    limit,
    source_name,
    start_date="",
    end_date="",
):
    _update_source_request_history_job(job_id, status="running", error="", history=[])
    export_path = ""
    try:
        if mode == "list":
            history = list_api_request_history(history_filters, limit=limit)
            _update_source_request_history_job(
                job_id,
                status="completed",
                history=history,
                row_count=len(history),
            )
            return

        if mode != "export":
            raise ValueError("Unsupported source request history job mode")

        rows = export_api_request_history(history_filters, limit=limit)
        filename = _build_source_request_history_filename(source_name, start_date, end_date)
        export_name = f"{job_id}_{secure_filename(filename) or 'source_request_history.csv'}"
        export_path = os.path.join(_SOURCE_REQUEST_HISTORY_EXPORT_DIR, export_name)
        with open(export_path, "w", encoding="utf-8-sig", newline="") as csv_file:
            _write_source_request_history_csv(csv_file, rows)
        _update_source_request_history_job(
            job_id,
            status="completed",
            row_count=len(rows),
            download_name=filename,
            file_path=export_path,
        )
    except Exception as exc:
        _remove_source_request_history_export_file(export_path)
        _update_source_request_history_job(
            job_id,
            status="error",
            error=str(exc),
            history=[],
            row_count=0,
            download_name="",
            file_path="",
        )


def _start_source_request_history_job(
    *,
    mode,
    history_filters,
    limit,
    source_name,
    start_date="",
    end_date="",
):
    _prune_source_request_history_jobs()
    job_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with _SOURCE_REQUEST_HISTORY_JOB_LOCK:
        _SOURCE_REQUEST_HISTORY_JOBS[job_id] = {
            "job_id": job_id,
            "owner_key": _source_request_history_owner_key(),
            "mode": mode,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "error": "",
            "history": [],
            "row_count": 0,
            "download_name": "",
            "file_path": "",
        }
    worker = threading.Thread(
        target=_run_source_request_history_job,
        kwargs={
            "job_id": job_id,
            "mode": mode,
            "history_filters": dict(history_filters or {}),
            "limit": limit,
            "source_name": source_name,
            "start_date": start_date,
            "end_date": end_date,
        },
        daemon=True,
    )
    worker.start()
    return _get_source_request_history_job_for_current_user(job_id)


def _build_source_request_history_job_context(settings, payload):
    mode = str(payload.get("mode") or "list").strip().lower()
    if mode not in {"list", "export"}:
        raise ValueError("Invalid source request history mode")

    try:
        source = _resolve_source_from_request(settings, payload=payload)
    except LookupError as exc:
        raise LookupError(str(exc))
    except ValueError as exc:
        raise ValueError(str(exc))

    request_definition = payload.get("request")
    if mode == "list" and not isinstance(request_definition, dict):
        raise ValueError("Missing request definition")

    start_date = str(payload.get("start_date") or "").strip()
    end_date = str(payload.get("end_date") or "").strip()
    history_filters = {"source_name": str(source.get("name") or "").strip()}
    if isinstance(request_definition, dict):
        history_filters.update(_source_request_history_filters(source, request_definition))
    history_filters.update(_history_date_range_filters(start_date, end_date))

    default_limit = 50000 if mode == "export" else 150
    max_limit = 50000 if mode == "export" else 5000
    limit = max(1, min(int(payload.get("limit") or default_limit), max_limit))
    return {
        "mode": mode,
        "source_name": str(source.get("name") or "").strip(),
        "start_date": start_date,
        "end_date": end_date,
        "history_filters": history_filters,
        "limit": limit,
    }


def _coerce_latest_value_timestamp(value):
    if value in (None, ""):
        return None
    try:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(cleaned)
            except ValueError:
                epoch = float(cleaned)
                if epoch > 1e12:
                    epoch /= 1000
                parsed = datetime.fromtimestamp(epoch, tz=timezone.utc)
        elif isinstance(value, (int, float)):
            epoch = float(value)
            if epoch > 1e12:
                epoch /= 1000
            parsed = datetime.fromtimestamp(epoch, tz=timezone.utc)
        else:
            return None
    except (TypeError, ValueError, OSError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_value_entry_timestamp(item, value_item=None):
    raw_ts = (
        (value_item or {}).get("ts")
        or (item or {}).get("ts")
        or (value_item or {}).get("updated_at")
        or (item or {}).get("updated_at")
    )
    return _coerce_latest_value_timestamp(raw_ts)


def _payload_latest_value_timestamp(payload):
    latest_ts = None
    items = _coerce_collection_items(payload)
    for item in items:
        if not isinstance(item, dict):
            continue
        values = item.get("values")
        if not isinstance(values, list):
            continue
        for value_item in values:
            if not isinstance(value_item, dict):
                continue
            parsed = _latest_value_entry_timestamp(item, value_item)
            if parsed is None:
                continue
            if latest_ts is None or parsed > latest_ts:
                latest_ts = parsed
    return latest_ts


def _latest_value_item_device_names(item):
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


def _latest_sensor_timestamps_by_device(device_ids, exclude_topic=None):
    normalized_device_ids = [str(device_id or "").strip() for device_id in device_ids if str(device_id or "").strip()]
    if not normalized_device_ids:
        return {}
    placeholders = ",".join("?" for _ in normalized_device_ids)
    params = list(normalized_device_ids)
    clauses = [f"device_id IN ({placeholders})"]
    if exclude_topic:
        clauses.append("(topic IS NULL OR topic != ?)")
        params.append(exclude_topic)
    query = f"""
        SELECT device_id, MAX(ts) AS max_ts
        FROM sensor_readings
        WHERE {' AND '.join(clauses)}
        GROUP BY device_id
    """
    with connect(SENSOR_DB) as conn:
        rows = conn.execute(query, params).fetchall()
    latest_by_device = {}
    for row in rows:
        parsed = _coerce_latest_value_timestamp(row["max_ts"])
        if parsed is not None:
            latest_by_device[row["device_id"]] = parsed
    return latest_by_device


def _filter_latest_history_payload_for_sensor_db(source_name, payload):
    latest_items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(latest_items, list):
        return {"items": []}

    normalized_source_name = str(source_name or "").strip()
    devices = data_service.get_devices()
    mapped_by_uuid = {}
    mapped_by_name = {}
    for device in devices:
        mapped_source_name = str(device.get("source_name") or "").strip()
        source_device_uuid = str(device.get("source_device_uuid") or "").strip()
        source_device_name = str(device.get("source_device_name") or "").strip()
        if source_device_uuid:
            mapped_by_uuid[(mapped_source_name, source_device_uuid)] = device
        if source_device_name:
            mapped_by_name[(mapped_source_name, source_device_name)] = device

    matched_items = []
    candidate_device_ids = []
    for item in latest_items:
        if not isinstance(item, dict):
            continue
        device_uuid = _latest_value_item_device_uuid(item)
        if not device_uuid:
            continue
        device_row = mapped_by_uuid.get((normalized_source_name, device_uuid))
        if not device_row:
            for candidate_name in _latest_value_item_device_names(item) + [device_uuid]:
                device_row = mapped_by_name.get((normalized_source_name, str(candidate_name or "").strip()))
                if device_row:
                    break
        if not device_row:
            continue
        matched_items.append((item, device_row))
        candidate_device_ids.append(device_row["device_id"])

    latest_by_device = _latest_sensor_timestamps_by_device(candidate_device_ids, exclude_topic="Test")
    filtered_items = []
    for item, device_row in matched_items:
        values = item.get("values")
        if not isinstance(values, list):
            continue
        device_latest_ts = latest_by_device.get(device_row["device_id"])
        if device_latest_ts is None:
            filtered_items.append(dict(item))
            continue
        filtered_values = []
        for value_item in values:
            if not isinstance(value_item, dict):
                continue
            entry_ts = _latest_value_entry_timestamp(item, value_item)
            if entry_ts is not None and entry_ts <= device_latest_ts:
                continue
            filtered_values.append(value_item)
        if not filtered_values:
            continue
        filtered_item = dict(item)
        filtered_item["values"] = filtered_values
        filtered_items.append(filtered_item)
    return {"items": filtered_items}


def _sync_latest_history_to_sensor_db(settings):
    for source in _normalize_endpoint_source_list(settings.get("endpoint_sources", [])):
        source_name = str(source.get("name") or "").strip()
        if not source_name:
            continue
        history_entry = latest_api_request_history(
            {
                "source_name": source_name,
                "request_role": "latest_values",
            }
        )
        if not history_entry or history_entry.get("response_status") != "success":
            continue
        payload = history_entry.get("response_payload") or {}
        filtered_payload = _filter_latest_history_payload_for_sensor_db(source_name, payload)
        if not _has_latest_value_payload(filtered_payload):
            continue
        try:
            fields_updated = data_service.sync_source_metric_fields(settings, source_name, payload)
            if fields_updated:
                settings_service.save_settings(settings)
            data_service.ingest_source_latest_values_payload(
                filtered_payload,
                source_name=source_name,
                settings=settings,
            )
        except Exception:
            continue


@app.route("/api/settings/source-devices", methods=["GET", "POST"])
def get_endpoint_source_devices():
    return preview_endpoint_source_data()


@app.post("/api/settings/source-token")
def get_endpoint_source_token():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    settings = settings_service.load_settings()
    payload = request.get_json(silent=True) or {}
    if isinstance(payload.get("sources"), list):
        settings["endpoint_sources"] = _normalize_endpoint_source_list(payload.get("sources"))

    try:
        source = _resolve_source_from_request(settings, payload=payload)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if source.get("format") != "api":
        return jsonify({"error": "Token fetch is only supported for API format sources"}), 400

    try:
        token = _fetch_source_token(source)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    source["token"] = token
    settings_updated = _save_shared_source_token(settings, source, token)
    if settings_updated:
        settings_service.save_settings(settings)

    return jsonify(
        {
            "token": token,
            "source": str(source.get("name") or "").strip(),
            "cache_key": _get_source_cache_key(source),
            "settings_updated": settings_updated,
        }
    )


@app.route("/api/settings/source-preview", methods=["GET", "POST"])
def preview_endpoint_source_data():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    settings = settings_service.load_settings()
    payload = request.get_json(silent=True) or {} if request.method == "POST" else {}
    if isinstance(payload.get("sources"), list):
        settings["endpoint_sources"] = _normalize_endpoint_source_list(payload.get("sources"))
    settings_updated = _sync_endpoint_token_store(settings)

    try:
        source = _resolve_source_from_request(
            settings,
            default_name="LIV-24 IAQ" if request.method == "GET" else "",
            payload=payload,
        )
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if source.get("format") != "api":
        return jsonify({"error": "Preview is only supported for API format sources"}), 400

    try:
        preview_payload = _load_source_preview_data(
            settings,
            source,
            payload.get("execution_state"),
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    ingest_result = preview_payload["source"].get("_latest_values_ingest_result", {"inserted": 0, "matched_devices": 0})
    settings_updated = settings_updated or bool(
        preview_payload["source"].get("_latest_values_settings_updated", False)
    )

    settings_updated = settings_updated or preview_payload.get("settings_updated", False)
    if settings_updated:
        settings_service.save_settings(settings)

    return jsonify(
        {
            "source": {
                "name": preview_payload["source"].get("name"),
                "format": preview_payload["source"].get("format"),
                "base_url": preview_payload["source"].get("base_url"),
                "token": preview_payload["source"].get("token"),
            },
            "cache_key": preview_payload.get("cache_key") or "",
            "organizations": preview_payload.get("organizations", []),
            "organization_items": preview_payload.get("organization_items", []),
            "devices": preview_payload.get("devices", []),
            "device_items": preview_payload.get("device_items", []),
            "ready_device_items": preview_payload.get("ready_device_items", []),
            "latest_values": preview_payload.get("latest_values", {"items": []}),
            "execution_state": preview_payload.get("execution_state", {}),
            "ingest_result": ingest_result,
            "source_metric_fields": data_service.get_source_metric_fields(settings),
        }
    )


@app.post("/api/settings/source-request-test")
def test_endpoint_source_request():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    settings = settings_service.load_settings()
    payload = request.get_json(silent=True) or {}
    if isinstance(payload.get("sources"), list):
        settings["endpoint_sources"] = _normalize_endpoint_source_list(payload.get("sources"))
    settings_updated = _sync_endpoint_token_store(settings)

    try:
        source = _resolve_source_from_request(settings, payload=payload)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if source.get("format") != "api":
        return jsonify({"error": "Request testing is only supported for API format sources"}), 400

    request_definition = payload.get("request")
    if not isinstance(request_definition, dict):
        return jsonify({"error": "Missing request definition"}), 400

    try:
        test_payload = _load_source_request_test_data(settings, source, request_definition)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    settings_updated = settings_updated or test_payload.get("settings_updated", False)
    if settings_updated:
        settings_service.save_settings(settings)

    return jsonify(
        {
            "source": {
                "name": test_payload["source"].get("name"),
                "format": test_payload["source"].get("format"),
                "base_url": test_payload["source"].get("base_url"),
                "token": test_payload["source"].get("token"),
            },
            "cache_key": test_payload.get("cache_key") or "",
            "request": test_payload.get("request", {}),
            "payload": test_payload.get("payload", {}),
            "organizations": test_payload.get("organizations", []),
            "organization_items": test_payload.get("organization_items", []),
            "devices": test_payload.get("devices", []),
            "device_items": test_payload.get("device_items", []),
            "history": list_api_request_history(
                _source_request_history_filters(source, request_definition),
                limit=10,
            ),
        }
    )


@app.post("/api/settings/source-request-history")
def get_endpoint_source_request_history():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    settings = settings_service.load_settings()
    payload = request.get_json(silent=True) or {}

    try:
        source = _resolve_source_from_request(settings, payload=payload)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    request_definition = payload.get("request")
    if not isinstance(request_definition, dict):
        return jsonify({"error": "Missing request definition"}), 400

    history_filters = _source_request_history_filters(source, request_definition)
    try:
        history_filters.update(
            _history_date_range_filters(
                payload.get("start_date"),
                payload.get("end_date"),
            )
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    history = list_api_request_history(
        history_filters,
        limit=payload.get("limit", 150),
    )
    return jsonify({"history": history})


@app.post("/api/settings/source-request-history/jobs")
def create_endpoint_source_request_history_job():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    settings = settings_service.load_settings()
    payload = request.get_json(silent=True) or {}

    try:
        job_context = _build_source_request_history_job_context(settings, payload)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    job = _start_source_request_history_job(**job_context)
    if not job:
        return jsonify({"error": "Failed to start source request history job"}), 500
    return jsonify(_serialize_source_request_history_job(job)), 202


@app.get("/api/settings/source-request-history/jobs/<job_id>")
def get_endpoint_source_request_history_job(job_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    job = _get_source_request_history_job_for_current_user(job_id)
    if not job:
        return jsonify({"error": "Source request history job not found"}), 404
    return jsonify(_serialize_source_request_history_job(job))


@app.get("/api/settings/source-request-history/jobs/<job_id>/download")
def download_endpoint_source_request_history_job(job_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    job = _get_source_request_history_job_for_current_user(job_id)
    if not job:
        return jsonify({"error": "Source request history job not found"}), 404
    if job.get("mode") != "export":
        return jsonify({"error": "Source request history job is not an export"}), 400
    if job.get("status") != "completed":
        return jsonify({"error": "Source request history export is not ready"}), 409

    file_path = str(job.get("file_path") or "").strip()
    if not file_path or not os.path.isfile(file_path):
        return jsonify({"error": "Source request history export file not found"}), 404

    return send_file(
        file_path,
        as_attachment=True,
        download_name=job.get("download_name") or os.path.basename(file_path),
        mimetype="text/csv",
    )


@app.get("/api/settings/source-request-history/export.csv")
def export_endpoint_source_request_history():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    source_name = str(request.args.get("source_name") or "").strip()
    if not source_name:
        return jsonify({"error": "Missing source_name"}), 400

    history_filters = {
        "source_name": source_name,
        "request_role": str(request.args.get("request_role") or "").strip().lower(),
        "request_name": str(request.args.get("request_name") or "").strip(),
        "request_method": str(request.args.get("request_method") or "").strip().upper(),
        "request_path": str(request.args.get("request_path") or "").strip(),
    }
    try:
        history_filters.update(
            _history_date_range_filters(
                request.args.get("start_date"),
                request.args.get("end_date"),
            )
        )
        rows = export_api_request_history(history_filters, limit=50000)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    csv_buffer = io.StringIO()
    _write_source_request_history_csv(csv_buffer, rows)
    csv_bytes = io.BytesIO(csv_buffer.getvalue().encode("utf-8-sig"))
    csv_bytes.seek(0)
    start_date = str(request.args.get("start_date") or "").strip()
    end_date = str(request.args.get("end_date") or "").strip()
    filename = _build_source_request_history_filename(source_name, start_date, end_date)
    return send_file(csv_bytes, as_attachment=True, download_name=filename, mimetype="text/csv")


@app.post("/api/settings/source-request-history/delete")
def delete_endpoint_source_request_history():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    payload = request.get_json(silent=True) or {}
    history_id = payload.get("history_id")
    if not history_id:
        return jsonify({"error": "Missing history_id"}), 400

    try:
        deleted = delete_api_request_history(history_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid history_id"}), 400

    if not deleted:
        return jsonify({"error": "History item not found"}), 404
    return jsonify({"success": True})


@app.get("/api/settings/source-device-cache")
def get_endpoint_source_device_cache():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    source_name = str(request.args.get("source_name") or "").strip()
    if not source_name:
        return jsonify({"error": "Missing source_name"}), 400

    settings = settings_service.load_settings()
    source = _find_source_by_name(settings, source_name)
    if source:
        try:
            preview_payload = _load_source_preview_data(settings, source)
            if preview_payload.get("settings_updated"):
                settings_service.save_settings(settings)
            ready_device_items = preview_payload.get("ready_device_items", [])
            return jsonify(
                {
                    "devices": preview_payload.get("devices", []),
                    "device_items": ready_device_items,
                    "ready_device_items": ready_device_items,
                    "all_device_items": preview_payload.get("device_items", []),
                    "latest_values": preview_payload.get("latest_values", {"items": []}),
                }
            )
        except Exception:
            pass

    history_entry = latest_api_request_history(
        {
            "source_name": source_name,
            "request_role": "devices",
        }
    )
    if not history_entry or history_entry.get("response_status") != "success":
        return jsonify({"devices": [], "device_items": [], "ready_device_items": []})

    payload = history_entry.get("response_payload", {})
    device_items = _coerce_collection_items(payload)
    return jsonify(
        {
            "devices": payload,
            "device_items": device_items,
            "ready_device_items": device_items,
            "created_at": history_entry.get("created_at") or "",
        }
    )


def _flatten_postman_items(items, parent_names=None):
    current_names = list(parent_names or [])
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("name") or "").strip()
        nested_names = current_names + ([item_name] if item_name else [])
        nested_items = item.get("item")
        if isinstance(nested_items, list):
            yield from _flatten_postman_items(nested_items, nested_names)
            continue
        request_payload = item.get("request")
        if isinstance(request_payload, dict):
            yield nested_names, request_payload


def _postman_variables(payload):
    variables = {}
    for item in payload.get("variable", []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("id") or "").strip()
        if not key:
            continue
        variables[key] = str(item.get("value") or "")
    return variables


def _postman_headers(headers, variables):
    normalized_headers = []
    if not isinstance(headers, list):
        return normalized_headers
    for header in headers:
        if not isinstance(header, dict) or header.get("disabled"):
            continue
        key = str(header.get("key") or "").strip()
        if not key:
            continue
        value = _render_template_placeholders(str(header.get("value") or ""), variables)
        normalized_headers.append({"key": key, "value": value})
    return normalized_headers


def _postman_query_items(query_items, variables):
    normalized_query = []
    if not isinstance(query_items, list):
        return normalized_query
    for item in query_items:
        if not isinstance(item, dict) or item.get("disabled"):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        value = _render_template_placeholders(str(item.get("value") or ""), variables)
        normalized_query.append({"key": key, "value": value})
    return normalized_query


def _postman_request_url(url_value, variables):
    raw_url = ""
    query_items = []

    if isinstance(url_value, str):
        raw_url = _render_template_placeholders(url_value, variables)
    elif isinstance(url_value, dict):
        raw_url = _render_template_placeholders(str(url_value.get("raw") or ""), variables)
        query_items = _postman_query_items(url_value.get("query"), variables)
        if not raw_url:
            protocol = str(url_value.get("protocol") or "https").strip()
            host = ".".join(
                _render_template_placeholders(str(part or ""), variables)
                for part in (url_value.get("host") or [])
                if str(part or "").strip()
            )
            path_segments = [
                _render_template_placeholders(str(part or ""), variables).strip("/")
                for part in (url_value.get("path") or [])
                if str(part or "").strip()
            ]
            path = "/".join(path_segments)
            if host:
                raw_url = f"{protocol}://{host}"
                if path:
                    raw_url = f"{raw_url}/{path}"
        if not query_items and raw_url:
            parsed = urlparse(raw_url)
            query_items = [{"key": key, "value": value} for key, value in parse_qsl(parsed.query)]

    parsed = urlparse(raw_url)
    origin = ""
    path_with_query = ""
    if parsed.scheme and parsed.netloc:
        origin = f"{parsed.scheme}://{parsed.netloc}"
        path_with_query = parsed.path or "/"
        if parsed.query:
            path_with_query = f"{path_with_query}?{parsed.query}"

    return {
        "url": raw_url,
        "origin": origin,
        "path": path_with_query,
        "query": query_items,
    }


def _guess_template_base_url(requests, variables):
    for key in ("baseUrl", "base_url", "hostUrl", "host_url", "apiBaseUrl", "api_base_url"):
        value = str(variables.get(key) or "").strip()
        if value:
            return value.rstrip("/")
    for request_definition in requests:
        origin = str(request_definition.get("origin") or "").strip()
        if origin:
            return origin.rstrip("/")
    return ""


def _find_template_request(requests, keywords, methods=None):
    allowed_methods = {method.upper() for method in methods} if methods else None
    for request_definition in requests:
        method = str(request_definition.get("method") or "GET").upper()
        if allowed_methods and method not in allowed_methods:
            continue
        haystack = " ".join(
            [
                str(request_definition.get("name") or ""),
                str(request_definition.get("url") or ""),
                str(request_definition.get("path") or ""),
            ]
        ).lower()
        if any(keyword in haystack for keyword in keywords):
            return request_definition
    return None


def _request_headers_object(headers, exclude_authorization=False):
    normalized = {}
    for item in headers or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "")
        if not key:
            continue
        if exclude_authorization and key.lower() == "authorization":
            continue
        normalized[key] = value
    return normalized


def _guess_query_key(request_definition, keywords, fallback):
    for item in request_definition.get("query", []) if isinstance(request_definition, dict) else []:
        key = str(item.get("key") or "").strip()
        if any(keyword in key.lower() for keyword in keywords):
            return key
    return fallback


def _path_or_url_for_template(request_definition):
    path_value = str(request_definition.get("path") or "").strip()
    return path_value or str(request_definition.get("url") or "").strip()


def _import_postman_collection(file_storage):
    collection_payload = json.load(file_storage.stream)
    variables = _postman_variables(collection_payload)
    requests = []

    for names, request_payload in _flatten_postman_items(collection_payload.get("item")):
        method = str(request_payload.get("method") or "GET").upper()
        url_definition = _postman_request_url(request_payload.get("url"), variables)
        request_name = " / ".join(part for part in names if part).strip() or f"Request {len(requests) + 1}"
        body = request_payload.get("body")
        raw_body = ""
        if isinstance(body, dict):
            raw_body = _render_template_placeholders(str(body.get("raw") or ""), variables)
        requests.append(
            {
                "id": uuid.uuid4().hex,
                "name": request_name,
                "method": method,
                "url": url_definition.get("url"),
                "origin": url_definition.get("origin"),
                "path": url_definition.get("path"),
                "query": url_definition.get("query"),
                "headers": _postman_headers(request_payload.get("header"), variables),
                "body": raw_body,
            }
        )

    if not requests:
        raise ValueError("Collection does not contain any requests")

    base_url = _guess_template_base_url(requests, variables)
    token_request = _find_template_request(
        requests,
        ("token", "login", "auth"),
        {"POST", "PUT", "PATCH", "GET"},
    )
    organizations_request = _find_template_request(requests, ("organization", "org"), {"GET"})
    devices_request = _find_template_request(requests, ("device",), {"GET"})
    latest_values_request = _find_template_request(
        requests,
        ("latest-values", "latest value", "latest_value", "telemetry", "value"),
        {"GET"},
    )

    template_name = str(
        ((collection_payload.get("info") or {}).get("name")) or file_storage.filename or "Imported Collection"
    ).strip()
    return {
        "id": uuid.uuid4().hex,
        "name": template_name,
        "source": str(file_storage.filename or "").strip(),
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "variables": variables,
        "requests": requests,
        "suggested": {
            "token_request_id": token_request.get("id") if token_request else "",
            "organizations_request_id": organizations_request.get("id") if organizations_request else "",
            "devices_request_id": devices_request.get("id") if devices_request else "",
            "latest_values_request_id": latest_values_request.get("id") if latest_values_request else "",
            "devices_org_param": _guess_query_key(devices_request, ("org", "organization"), "org_uuid")
            if devices_request
            else "org_uuid",
            "latest_values_device_param": _guess_query_key(
                latest_values_request,
                ("device", "device_uuid", "device_id"),
                "device_uuid",
            )
            if latest_values_request
            else "device_uuid",
            "request_headers": _request_headers_object(
                (latest_values_request or devices_request or organizations_request or {}).get("headers", []),
                exclude_authorization=True,
            ),
            "token_field": "access_token",
            "token_url": _path_or_url_for_template(token_request) if token_request else "",
            "token_method": str(token_request.get("method") or "POST") if token_request else "POST",
            "token_headers": _request_headers_object(
                (token_request or {}).get("headers", []),
                exclude_authorization=False,
            ),
            "token_body": str((token_request or {}).get("body") or ""),
            "organizations_path": _path_or_url_for_template(organizations_request)
            if organizations_request
            else "",
            "devices_path": _path_or_url_for_template(devices_request) if devices_request else "",
            "latest_values_path": _path_or_url_for_template(latest_values_request)
            if latest_values_request
            else "",
        },
    }


@app.route("/settings", methods=["GET", "POST"])
@require_page_access("settings")
def settings():
    settings = settings_service.load_settings()
    if _sync_endpoint_token_store(settings):
        settings_service.save_settings(settings)
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
    active_settings_tab = str(request.args.get("tab") or "project").strip().lower()
    if active_settings_tab not in {"project", "source", "design", "user"}:
        active_settings_tab = "project"
    previous_sensor_icon = settings.get("sensor_icon", "")
    endpoint_sources = settings.get("endpoint_sources", [])
    role_permissions = settings.get("role_permissions", {})
    if request.method == "POST":
        settings_section = str(request.form.get("settings_section") or "project").strip().lower()
        if settings_section not in {"project", "source", "design", "user"}:
            settings_section = "project"

        if settings_section == "project":
            settings["project_name"] = request.form.get("project_name", settings["project_name"])
            settings["location_label"] = request.form.get("location_label", settings["location_label"])
            settings["project_timezone"] = get_project_timezone_name(
                {"project_timezone": request.form.get("project_timezone", settings.get("project_timezone", "Asia/Bangkok"))}
            )
            settings["project_time_format"] = get_project_time_format(
                {"project_time_format": request.form.get("project_time_format", settings.get("project_time_format", "24h"))}
            )
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

        if settings_section == "source":
            settings["endpoint_sources"] = _parse_endpoint_sources(request.form)
            _sync_endpoint_token_store(settings)

        if settings_section == "design":
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

            def parse_map_count(value, fallback):
                try:
                    count = int(value)
                except (TypeError, ValueError):
                    return fallback
                return max(1, count)

            existing_dashboard_cards = modules.get("dashboard_cards", {})
            updated_dashboard_cards = {}
            for system_key in settings_service.SYSTEM_KEYS:
                existing_cards = existing_dashboard_cards.get(system_key, {})
                fallback_count = existing_cards.get("map_count", 1)
                updated_dashboard_cards[system_key] = {
                    "map": bool(request.form.get(f"dashboard_card_map_{system_key}")),
                    "map_count": parse_map_count(
                        request.form.get(f"dashboard_card_map_count_{system_key}"),
                        fallback_count,
                    ),
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

        if settings_section == "design":
            source_metric_fields = []
            source_metric_keys = request.form.getlist("source_metric_field_key")
            for raw_key in source_metric_keys:
                metric_key = data_service._normalize_source_metric_field_key(raw_key)
                if not metric_key:
                    continue
                source_metric_fields.append(
                    {
                        "key": metric_key,
                        "source_field": (
                            request.form.get(f"source_metric_source_field__{metric_key}")
                            or raw_key
                            or metric_key
                        ).strip(),
                        "label": (
                            request.form.get(f"source_metric_label__{metric_key}")
                            or data_service._default_source_metric_label(raw_key)
                        ).strip(),
                        "channel": (
                            request.form.get(f"source_metric_channel__{metric_key}") or ""
                        ).strip(),
                        "unit": (
                            request.form.get(f"source_metric_unit__{metric_key}")
                            or data_service.SOURCE_METRIC_UNITS.get(metric_key, "")
                        ).strip(),
                        "show_in_bulk_type": bool(
                            request.form.get(f"source_metric_show_in_bulk_type__{metric_key}")
                        ),
                        "show_in_tooltip": bool(
                            request.form.get(f"source_metric_show_in_tooltip__{metric_key}")
                        ),
                        "save_to_db": bool(
                            request.form.get(f"source_metric_save_to_db__{metric_key}")
                        ),
                        "enable_severity": bool(
                            request.form.get(f"source_metric_enable_severity__{metric_key}")
                        ),
                        "sources": [
                            item.strip()
                            for item in (
                                request.form.get(f"source_metric_sources__{metric_key}") or ""
                            ).split(",")
                            if item.strip()
                        ],
                    }
                )
            settings["source_metric_fields"] = sorted(
                source_metric_fields,
                key=lambda item: (item.get("label") or item.get("key") or "").lower(),
            )

            severity_labels = request.form.getlist("severity_label")
            severity_colors = request.form.getlist("severity_color")
            severity_icons = request.form.getlist("severity_icon")
            severity_temperatures = request.form.getlist("severity_temperature")
            severity_humidity = request.form.getlist("severity_humidity")
            severity_pm25 = request.form.getlist("severity_pm25")
            severity_pm10 = request.form.getlist("severity_pm10")
            severity_tvoc = request.form.getlist("severity_tvoc")
            severity_co2 = request.form.getlist("severity_co2")
            dynamic_severity_fields = [
                field
                for field in source_metric_fields
                if field.get("enable_severity")
                and field.get("key") not in data_service.METRIC_ORDER
            ]
            dynamic_severity_values = {
                field["key"]: request.form.getlist(f"severity_dynamic__{field['key']}")
                for field in dynamic_severity_fields
            }
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
                                **{
                                    field["key"]: parse_float(
                                        (
                                            dynamic_severity_values.get(field["key"], [])[len(severity_levels)]
                                            if len(dynamic_severity_values.get(field["key"], [])) > len(severity_levels)
                                            else None
                                        )
                                    )
                                    for field in dynamic_severity_fields
                                },
                            },
                        }
                    )
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
            next_sensor_icon = settings.get("sensor_icon", "")
            if previous_sensor_icon and next_sensor_icon != previous_sensor_icon:
                data_service.set_sensor_icon_for_missing(previous_sensor_icon)

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

        if settings_section == "user":
            user_action = str(request.form.get("user_action") or "").strip()
            try:
                if user_action == "create_user":
                    new_user_role = auth_service.normalize_role(request.form.get("new_user_role"))
                    if new_user_role not in role_permissions:
                        raise ValueError("Selected role is not available")
                    auth_service.create_user(
                        username=request.form.get("new_user_username"),
                        password=request.form.get("new_user_password"),
                        full_name=request.form.get("new_user_full_name"),
                        role=new_user_role,
                    )
                elif user_action == "create_role":
                    new_role_name = settings_service.normalize_role_name(
                        request.form.get("new_role_name"),
                        default="",
                    )
                    if not new_role_name:
                        raise ValueError("Role name is required")
                    if new_role_name in role_permissions:
                        raise ValueError("Role already exists")
                    role_permissions[new_role_name] = {
                        page_key: bool(request.form.get(f"new_role_permission__{page_key}"))
                        for page_key in ROLE_PAGE_KEYS
                    }
                    settings["role_permissions"] = role_permissions
                    settings_service.normalize_role_permissions(settings)
                elif user_action.startswith("save_role_permissions:"):
                    role_name = settings_service.normalize_role_name(
                        user_action.split(":", 1)[1],
                        default="",
                    )
                    if not role_name or role_name not in role_permissions:
                        raise ValueError("Role not found")
                    updated_permissions = {
                        page_key: bool(request.form.get(f"role_permission__{role_name}__{page_key}"))
                        for page_key in ROLE_PAGE_KEYS
                    }
                    if role_name == "admin":
                        updated_permissions = {page_key: True for page_key in ROLE_PAGE_KEYS}
                    role_permissions[role_name] = updated_permissions
                    settings["role_permissions"] = role_permissions
                    settings_service.normalize_role_permissions(settings)
                elif user_action.startswith("delete_role:"):
                    role_name = settings_service.normalize_role_name(
                        user_action.split(":", 1)[1],
                        default="",
                    )
                    if role_name == "admin":
                        raise ValueError("Admin role cannot be deleted")
                    if not role_name or role_name not in role_permissions:
                        raise ValueError("Role not found")
                    assigned_user = next(
                        (
                            user
                            for user in auth_service.list_users()
                            if auth_service.normalize_role(user["role"]) == role_name
                        ),
                        None,
                    )
                    if assigned_user:
                        raise ValueError("Cannot delete a role that is assigned to users")
                    role_permissions.pop(role_name, None)
                    settings["role_permissions"] = role_permissions
                elif user_action.startswith("change_role:"):
                    user_id = int(user_action.split(":", 1)[1])
                    selected_role = auth_service.normalize_role(request.form.get(f"user_role__{user_id}"))
                    if selected_role not in role_permissions:
                        raise ValueError("Selected role is not available")
                    auth_service.update_user_role(
                        user_id,
                        selected_role,
                    )
                    if session.get("user_id") == user_id:
                        session["role"] = selected_role
                        session["is_admin"] = session["role"] == "admin"
                elif user_action.startswith("change_password:"):
                    user_id = int(user_action.split(":", 1)[1])
                    auth_service.update_user_password(
                        user_id,
                        request.form.get(f"user_password__{user_id}"),
                    )
                elif user_action.startswith("delete_user:"):
                    user_id = int(user_action.split(":", 1)[1])
                    if session.get("user_id") == user_id:
                        raise ValueError("You cannot delete the current login user")
                    auth_service.delete_user(user_id)
            except ValueError as exc:
                flash(str(exc), "danger")
            else:
                if user_action:
                    flash("User settings updated.", "success")

        settings_service.save_settings(settings)
        return redirect(url_for("settings", tab=settings_section))

    device_payloads = [dict(device) for device in devices]

    try:
        login_history_start_date = _normalize_history_date_text(
            request.args.get("login_history_start_date")
        )
        login_history_end_date = _normalize_history_date_text(
            request.args.get("login_history_end_date")
        )
    except ValueError:
        flash("Invalid login history date format.", "danger")
        login_history_start_date = ""
        login_history_end_date = ""
    login_history_limit = 10 if not (login_history_start_date or login_history_end_date) else None

    return render_template(
        "settings.html",
        settings=settings,
        available_uploads=available_uploads,
        floors=floors,
        devices=device_payloads,
        default_system=default_system,
        endpoint_sources=endpoint_sources,
        active_settings_tab=active_settings_tab,
        default_endpoint_source=settings_service.normalize_endpoint_source_definition({}),
        managed_users=auth_service.list_users(),
        role_permissions=role_permissions,
        role_page_keys=ROLE_PAGE_KEYS,
        login_history=auth_service.list_login_history(
            login_history_limit,
            start_date=login_history_start_date,
            end_date=login_history_end_date,
        ),
        login_history_start_date=login_history_start_date,
        login_history_end_date=login_history_end_date,
        source_metric_fields=data_service.get_source_metric_fields(settings),
        dynamic_severity_fields=[
            field
            for field in data_service.get_source_metric_fields(settings)
            if field.get("enable_severity")
            and field.get("key") not in data_service.METRIC_ORDER
        ],
        bulk_sensor_type_options=sorted(
            {
                (field.get("source_field") or field.get("key") or "").strip()
                for field in data_service.get_source_metric_fields(settings)
                if field.get("show_in_bulk_type")
            }
            | {
                extract_sensor_type_from_label(device.get("label"))
                for device in device_payloads
                if extract_sensor_type_from_label(device.get("label"))
            }
        ),
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
    settings = settings_service.load_settings()
    device = data_service.create_device(
        floor_id,
        zone=zone or "Z1",
        sensor_type=sensor_type or "DZ",
        sensor_name=sensor_name,
        sensor_icon=settings.get("sensor_icon"),
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

@app.post("/api/devices/<device_id>/source-mapping")
def update_device_source_mapping(device_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(silent=True) or {}
    source_name = (payload.get("source_name") or "").strip() or None
    source_device_name = (payload.get("source_device_name") or "").strip() or None
    source_device_uuid = (payload.get("source_device_uuid") or "").strip() or None
    data_service.update_device_source_mapping(
        device_id,
        source_name,
        source_device_name,
        source_device_uuid,
    )
    return jsonify(
        {
            "device_id": device_id,
            "source_name": source_name,
            "source_device_name": source_device_name,
            "source_device_uuid": source_device_uuid,
        }
    )



@app.post("/api/devices/<device_id>/sensor-types")
def update_device_sensor_types(device_id):
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(silent=True) or {}
    sensor_types = data_service.normalize_device_sensor_types(payload.get("sensor_types"))
    data_service.update_device_sensor_types(device_id, sensor_types)
    return jsonify({"device_id": device_id, "sensor_types": sensor_types})


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
    auth_service.ensure_default_admin_user(settings)
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = auth_service.authenticate_user(username, password)
        if user and str(user["role"] or "admin").strip().lower() == "admin":
            session["is_admin"] = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = auth_service.normalize_role(user["role"])
            auth_service.log_login_attempt(
                attempted_username=username,
                user=user,
                success=True,
                ip_address=get_request_ip(),
                location_text=get_request_location_text(),
                request_method=request.method,
                request_path=request.path,
                user_agent=request.headers.get("User-Agent", ""),
                session_id=request.cookies.get(app.config.get("SESSION_COOKIE_NAME", "session"), ""),
            )
            return redirect(url_for(get_first_accessible_endpoint(settings)))
        elif user:
            session["is_admin"] = False
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = auth_service.normalize_role(user["role"])
            auth_service.log_login_attempt(
                attempted_username=username,
                user=user,
                success=True,
                ip_address=get_request_ip(),
                location_text=get_request_location_text(),
                request_method=request.method,
                request_path=request.path,
                user_agent=request.headers.get("User-Agent", ""),
                session_id=request.cookies.get(app.config.get("SESSION_COOKIE_NAME", "session"), ""),
            )
            return redirect(url_for(get_first_accessible_endpoint(settings)))
        auth_service.log_login_attempt(
            attempted_username=username,
            success=False,
            ip_address=get_request_ip(),
            location_text=get_request_location_text(),
            request_method=request.method,
            request_path=request.path,
            user_agent=request.headers.get("User-Agent", ""),
            session_id=request.cookies.get(app.config.get("SESSION_COOKIE_NAME", "session"), ""),
        )
        error = translate_text("invalid_credentials")
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    init_all()
    seed_demo_data()
    _ensure_background_source_polling_started()
    app.run(
        debug=_env_flag("ICON_DEBUG", default=True),
        host=os.environ.get("ICON_HOST", "0.0.0.0"),
        port=int(os.environ.get("ICON_PORT", "5000")),
    )
