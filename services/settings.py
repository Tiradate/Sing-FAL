import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")

DEFAULT_SETTINGS = {
    "project_name": "ICONSIAM",
    "location_label": "Bangkok, Thailand",
    "floor_auto_rotate_seconds": 12,
    "show_icons": {
        "bell": True,
        "calendar": True,
        "download": True,
        "settings": True,
    },
    "severity_levels": [
        {"label": "Good", "color": "#28a745", "icon": "bi-emoji-smile"},
        {"label": "Moderate", "color": "#fd7e14", "icon": "bi-exclamation-circle"},
        {"label": "Unhealthy", "color": "#dc3545", "icon": "bi-exclamation-triangle"},
    ],
    "critical_levels": ["Unhealthy"],
    "floor_plans": {
        "F1": "static/uploads/floor_f1.svg",
        "F2": "static/uploads/floor_f2.svg",
    },
    "sensor_icon": "static/uploads/sensor_icon.svg",
    "sensor_icon_size": 28,
    "admin_username": "admin",
    "admin_password": "admin123",
}


def load_settings():
    if not os.path.exists(SETTINGS_PATH):
        save_settings(DEFAULT_SETTINGS)
    with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_settings(settings):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
