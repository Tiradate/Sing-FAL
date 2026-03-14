import copy
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")

SYSTEM_KEYS = ("iaq", "energy", "waste", "fire")

DEFAULT_TOP_DEFINITION = {
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

DEFAULT_DASHBOARD_CARDS = {
    "map": True,
    "map_count": 1,
    "daily_graph": True,
    "weekly_overview": True,
    "sensor_average": True,
    "alerts_notifications": True,
}

DEFAULT_TAG_VISIBILITY = {
    "iaq": {
        "temperature": True,
        "pm25": True,
        "pm10": True,
        "humidity": True,
        "tvoc": True,
        "co2": True,
    },
    "fire": {
        "smoke": True,
        "heat": True,
        "flow_switch": True,
        "supervisory_valve": True,
        "manual": True,
        "gas": True,
    },
}

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
    "tag_visibility": DEFAULT_TAG_VISIBILITY,
    "system_navigation": {
        "iaq": True,
        "energy": True,
        "waste": True,
        "fire": True,
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
            "iaq": DEFAULT_TOP_DEFINITION,
            "energy": {
                **DEFAULT_TOP_DEFINITION,
                "enabled": False,
                "header": "Energy & Carbon Overview",
            },
            "waste": {
                **DEFAULT_TOP_DEFINITION,
                "enabled": False,
                "header": "Waste Overview",
            },
            "fire": {
                **DEFAULT_TOP_DEFINITION,
                "header": "Average Indoor/Outdoor Fire Status",
            },
        },
        "dashboard_cards": {
            "iaq": {**DEFAULT_DASHBOARD_CARDS},
            "energy": {**DEFAULT_DASHBOARD_CARDS},
            "waste": {**DEFAULT_DASHBOARD_CARDS},
            "fire": {**DEFAULT_DASHBOARD_CARDS},
        },
    },
    "admin_username": "admin",
    "admin_password": "admin123",
    "endpoint_sources": [
        {
            "name": "LIV-24 IAQ",
            "format": "api",
            "base_url": "",
            "token": "",
            "mqtt": {
                "host": "",
                "port": 1883,
                "username": "",
                "password": "",
                "topic": "",
            },
        }
    ],
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

    updated = _merge_defaults(settings, DEFAULT_SETTINGS)
    updated = normalize_top_definition(settings) or updated
    updated = normalize_dashboard_cards(settings) or updated
    if updated:
        save_settings(settings)
    return settings


def normalize_top_definition(settings):
    modules = settings.setdefault("modules", {})
    top_definition = modules.get("top_definition", {})
    default_map = DEFAULT_SETTINGS["modules"]["top_definition"]
    updated = False

    if not isinstance(top_definition, dict):
        modules["top_definition"] = default_map
        return True

    legacy_keys = {"enabled", "title", "header", "columns", "mode", "legend"}
    if legacy_keys.intersection(top_definition.keys()):
        normalized = {key: copy.deepcopy(default_map[key]) for key in SYSTEM_KEYS}
        for key in ("iaq", "fire"):
            normalized[key] = {
                **copy.deepcopy(default_map[key]),
                **top_definition,
            }
        modules["top_definition"] = normalized
        return True

    normalized = {}
    for key in SYSTEM_KEYS:
        current = top_definition.get(key, {})
        merged = copy.deepcopy(default_map.get(key, DEFAULT_TOP_DEFINITION))
        if isinstance(current, dict):
            merged.update(current)
            if "columns" in merged and isinstance(current.get("columns"), dict):
                merged["columns"] = {
                    **merged.get("columns", {}),
                    **current.get("columns", {}),
                }
        normalized[key] = merged
        if current != merged:
            updated = True
    if updated or top_definition != normalized:
        modules["top_definition"] = normalized
        updated = True

    return updated


def normalize_dashboard_cards(settings):
    modules = settings.setdefault("modules", {})
    dashboard_cards = modules.get("dashboard_cards", {})
    default_map = DEFAULT_SETTINGS["modules"]["dashboard_cards"]
    updated = False

    if not isinstance(dashboard_cards, dict):
        modules["dashboard_cards"] = default_map
        return True

    legacy_keys = {
        "daily_graph",
        "weekly_overview",
        "sensor_average",
        "alerts_notifications",
    }
    if legacy_keys.intersection(dashboard_cards.keys()):
        normalized = {key: copy.deepcopy(default_map[key]) for key in SYSTEM_KEYS}
        for key in ("iaq", "fire"):
            normalized[key] = {
                **copy.deepcopy(default_map[key]),
                **dashboard_cards,
            }
        modules["dashboard_cards"] = normalized
        return True

    normalized = {}
    for key in SYSTEM_KEYS:
        current = dashboard_cards.get(key, {})
        merged = copy.deepcopy(default_map.get(key, DEFAULT_DASHBOARD_CARDS))
        if isinstance(current, dict):
            merged.update(current)
        normalized[key] = merged
        if current != merged:
            updated = True

    if updated or dashboard_cards != normalized:
        modules["dashboard_cards"] = normalized
        updated = True

    return updated


def save_settings(settings):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
