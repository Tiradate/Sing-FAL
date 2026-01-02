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
        {
            "label": "Good",
            "color": "#28a745",
            "icon": "bi-emoji-smile",
            "thresholds": {
                "temperature": 24,
                "humidity": 60,
                "pm25": 15,
                "pm10": 45,
                "tvoc": 0.5,
                "co2": 1000,
            },
        },
        {
            "label": "Moderate",
            "color": "#fd7e14",
            "icon": "bi-exclamation-circle",
            "thresholds": {
                "temperature": 27,
                "humidity": 70,
                "pm25": 35,
                "pm10": 75,
                "tvoc": 1.0,
                "co2": 1500,
            },
        },
        {
            "label": "Unhealthy",
            "color": "#dc3545",
            "icon": "bi-exclamation-triangle",
            "thresholds": {
                "temperature": 30,
                "humidity": 80,
                "pm25": 55,
                "pm10": 150,
                "tvoc": 2.0,
                "co2": 2000,
            },
        },
    ],
    "critical_levels": ["Unhealthy"],
    "floor_plans": {
        "F1": "static/uploads/floor_f1.svg",
        "F2": "static/uploads/floor_f2.svg",
    },
    "sensor_icon": "static/uploads/sensor_icon.svg",
    "sensor_icon_size": 28,
    "project_logo": "",
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
