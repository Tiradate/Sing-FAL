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
    "show_severity_lines": True,
    "system_navigation": {
        "iaq": True,
        "energy": False,
        "waste": False,
        "fire": False,
    },
    "fire_severity_mapping": [],
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
    "floor_plans": {},
    "sensor_icon": "static/uploads/sensor_icon.svg",
    "sensor_icon_size": 28,
    "floor_logo_icon": "static/uploads/logo_icon.svg",
    "logo_icon_size": 32,
    "project_logo": "",
    "floor_plan_logos": {},
    "card_header_color": "#ffffff",
    "card_body_color": "#ffffff",
    "page_background_color": "#f8f9fa",
    "modules": {
        "top_definition": {
            "enabled": True,
            "title": "Top Definition",
            "header": "Average Indoor/Outdoor IAQ",
            "columns": {
                "indoor": "Indoor",
                "outdoor": "Outdoor",
                "indoor_enabled": True,
                "outdoor_enabled": True,
            },
            "mode": "average",
            "legend": [
                {"label": "Good", "color": "#28a745"},
                {"label": "Moderate", "color": "#fd7e14"},
                {"label": "Unhealthy", "color": "#dc3545"},
            ],
        }
    },
    "admin_username": "admin",
    "admin_password": "admin123",
}


def _merge_defaults(target, defaults, parent_key=""):
    updated = False
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
            updated = True
        elif isinstance(value, dict) and isinstance(target.get(key), dict) and key != "floor_plans":
            nested_updated = _merge_defaults(target[key], value, key)
            updated = updated or nested_updated
    return updated


def load_settings():
    if not os.path.exists(SETTINGS_PATH):
        save_settings(DEFAULT_SETTINGS)
    with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
        settings = json.load(handle)

    if _merge_defaults(settings, DEFAULT_SETTINGS):
        save_settings(settings)
    return settings


def save_settings(settings):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
