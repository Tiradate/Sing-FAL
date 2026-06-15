import copy
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.environ.get("ICON_DATA_DIR") or BASE_DIR
os.makedirs(DATA_DIR, exist_ok=True)
SETTINGS_PATH = os.environ.get("ICON_SETTINGS_PATH") or os.path.join(DATA_DIR, "settings.json")

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
    "psychrometric_chart": True,
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

DEFAULT_ENDPOINT_API = {
    "template_id": "",
    "request_headers": "{}",
    "auth_type": "none",
    "token_url": "",
    "token_method": "POST",
    "token_field": "access_token",
    "auth_username": "",
    "auth_password": "",
    "auth_headers": "{}",
    "auth_body": '{\n  "username": "{{username}}",\n  "password": "{{password}}"\n}',
    "api_key_name": "",
    "api_key_value": "",
    "custom_auth_headers": "{}",
    "requests": [
        {
            "id": "organizations",
            "role": "organizations",
            "name": "Organizations",
            "method": "GET",
            "path": "/api/external/v1/organizations",
            "params": [],
            "body": "",
            "use_auth": True,
            "max_round_times": 0,
            "max_interval_minutes": 0,
            "interval_unlimited": True,
            "run_every_times": 0,
            "run_interval_minutes": 0,
        },
        {
            "id": "devices",
            "role": "devices",
            "name": "Devices",
            "method": "GET",
            "path": "/api/external/v1/devices",
            "params": [{"key": "org_uuid", "value": "{{organization_uuid}}"}],
            "body": "",
            "use_auth": True,
            "max_round_times": 0,
            "max_interval_minutes": 0,
            "interval_unlimited": True,
            "run_every_times": 0,
            "run_interval_minutes": 0,
        },
        {
            "id": "latest_values",
            "role": "latest_values",
            "name": "Latest Values",
            "method": "GET",
            "path": "/api/external/v1/latest-values",
            "params": [{"key": "device_uuid", "values": ["{{device_uuid}}"]}],
            "body": "",
            "use_auth": True,
            "max_round_times": 0,
            "max_interval_minutes": 0,
            "interval_unlimited": True,
            "run_every_times": 0,
            "run_interval_minutes": 0,
        },
        {
            "id": "history",
            "role": "history",
            "name": "History",
            "method": "GET",
            "path": "/api/external/v1/history",
            "params": [
                {"key": "device_uuid", "values": ["{{device_uuid}}"]},
                {"key": "aggregation", "values": ["raw"]},
                {"key": "fields", "values": ["all"]},
                {"key": "lookback_seconds", "values": ["86400"]},
            ],
            "body": "",
            "use_auth": True,
            "max_round_times": 0,
            "max_interval_minutes": 0,
            "interval_unlimited": True,
            "run_every_times": 0,
            "run_interval_minutes": 0,
        },
        {
            "id": "history_export",
            "role": "history_export",
            "name": "History Export",
            "method": "GET",
            "path": "/api/external/v1/history/export",
            "params": [
                {"key": "device_uuid", "values": ["{{device_uuid}}"]},
                {"key": "aggregation", "values": ["raw"]},
                {"key": "fields", "values": ["all"]},
            ],
            "body": "",
            "use_auth": True,
            "max_round_times": 0,
            "max_interval_minutes": 0,
            "interval_unlimited": True,
            "run_every_times": 0,
            "run_interval_minutes": 0,
        },
    ],
}

DEFAULT_ENDPOINT_MQTT = {
    "host": "",
    "port": 1883,
    "username": "",
    "password": "",
    "topic": "",
}

DEFAULT_ENDPOINT_SERIAL = {
    "port": "",
    "baudrate": 9600,
    "read_timeout_ms": 1000,
    "preview_line_limit": 100,
    "device_key_mode": "pcd_first",
    "replay_file_path": "",
    "replay_interval_seconds": 60,
}

DEFAULT_ENDPOINT_SOURCE = {
    "name": "LIV-24 IAQ",
    "format": "api",
    "base_url": "",
    "token": "",
    "api": DEFAULT_ENDPOINT_API,
    "mqtt": DEFAULT_ENDPOINT_MQTT,
    "serial": DEFAULT_ENDPOINT_SERIAL,
}

DEFAULT_ROLE_PERMISSIONS = {
    "admin": {
        "home": True,
        "alarms": True,
        "map": True,
        "settings": True,
    },
    "manager": {
        "home": True,
        "alarms": True,
        "map": False,
        "settings": False,
    },
    "guest": {
        "home": False,
        "alarms": False,
        "map": True,
        "settings": False,
    },
}

DEFAULT_ACCOUNTING_SETTINGS = {
    "enabled": True,
    "business_type": "General Business",
    "base_currency": "THB",
    "reporting_basis": "accrual",
    "fiscal_year_start_month": 1,
    "default_credit_term_days": 30,
    "tax_rate": 7.0,
    "tax_mode": "vat",
    "lock_date": "",
    "modules": {
        "chart_of_accounts": {
            "enabled": True,
            "assets": True,
            "liabilities": True,
            "income": True,
            "expenses": True,
            "customize_by_business_type": True,
        },
        "transactions": {
            "enabled": True,
            "sales_invoice": True,
            "purchase_invoice": True,
            "payment_entry": True,
            "journal_entry": True,
        },
        "receivables_payables": {
            "enabled": True,
            "accounts_receivable": True,
            "accounts_payable": True,
            "credit_terms": True,
            "payment_reminders": True,
        },
        "taxes": {
            "enabled": True,
            "vat": True,
            "sales_tax": True,
            "purchase_tax": True,
            "multi_structure": True,
            "auto_apply": True,
        },
        "financial_reports": {
            "enabled": True,
            "profit_and_loss": True,
            "balance_sheet": True,
            "cash_flow": True,
            "general_ledger": True,
            "trial_balance": True,
            "real_time": True,
        },
        "period_closing": {
            "enabled": True,
            "monthly_close": True,
            "yearly_close": True,
            "lock_backdated_entries": True,
        },
        "integrations": {
            "enabled": True,
            "sales": True,
            "purchase": True,
            "stock": True,
            "payroll": True,
            "auto_posting": True,
        },
    },
}

DEFAULT_SETTINGS = {
    "project_name": "ICONSIAM",
    "location_label": "Bangkok, Thailand",
    "project_timezone": "Asia/Bangkok",
    "project_time_format": "24h",
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
    "accounting": DEFAULT_ACCOUNTING_SETTINGS,
    "role_permissions": DEFAULT_ROLE_PERMISSIONS,
    "endpoint_sources": [DEFAULT_ENDPOINT_SOURCE],
    "endpoint_token_store": {},
    "endpoint_api_templates": [],
    "source_metric_fields": [],
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
    updated = normalize_accounting_settings(settings) or updated
    updated = normalize_role_permissions(settings) or updated
    updated = normalize_endpoint_sources(settings) or updated
    updated = normalize_endpoint_api_templates(settings) or updated
    updated = normalize_endpoint_token_store(settings) or updated
    if updated:
        save_settings(settings)
    return settings


def normalize_endpoint_source_definition(source):
    normalized = copy.deepcopy(DEFAULT_ENDPOINT_SOURCE)
    if not isinstance(source, dict):
        return normalized

    for key in ("name", "format", "base_url", "token"):
        if key in source:
            normalized[key] = source.get(key)

    api_config = source.get("api")
    raw_api_config = api_config if isinstance(api_config, dict) else {}
    if raw_api_config:
        normalized["api"].update(raw_api_config)
    normalized["api"] = normalize_endpoint_api_definition(normalized["api"])
    if raw_api_config and not isinstance(raw_api_config.get("requests"), list):
        normalized["api"]["requests"] = [
            normalize_endpoint_api_request_definition(request_definition, index)
            for index, request_definition in enumerate(_legacy_endpoint_api_requests(normalized["api"]))
        ]
    if (
        str(normalized.get("token") or "").strip()
        and normalized["api"].get("auth_type") == "none"
        and not str(normalized["api"].get("token_url") or "").strip()
    ):
        normalized["api"]["auth_type"] = "bearer_token"

    mqtt_config = source.get("mqtt")
    if isinstance(mqtt_config, dict):
        normalized["mqtt"].update(mqtt_config)

    serial_config = source.get("serial")
    if isinstance(serial_config, dict):
        normalized["serial"].update(serial_config)

    source_format = str(normalized.get("format") or "api").strip().lower()
    normalized["format"] = source_format if source_format in ("api", "mqtt", "serial") else "api"

    try:
        normalized["mqtt"]["port"] = int(normalized["mqtt"].get("port") or 1883)
    except (TypeError, ValueError):
        normalized["mqtt"]["port"] = 1883

    try:
        normalized["serial"]["baudrate"] = int(normalized["serial"].get("baudrate") or 9600)
    except (TypeError, ValueError):
        normalized["serial"]["baudrate"] = 9600

    try:
        normalized["serial"]["read_timeout_ms"] = int(
            normalized["serial"].get("read_timeout_ms") or 1000
        )
    except (TypeError, ValueError):
        normalized["serial"]["read_timeout_ms"] = 1000

    try:
        normalized["serial"]["preview_line_limit"] = int(
            normalized["serial"].get("preview_line_limit") or 100
        )
    except (TypeError, ValueError):
        normalized["serial"]["preview_line_limit"] = 100

    try:
        normalized["serial"]["replay_interval_seconds"] = int(
            normalized["serial"].get("replay_interval_seconds") or 60
        )
    except (TypeError, ValueError):
        normalized["serial"]["replay_interval_seconds"] = 60

    normalized["serial"]["port"] = str(normalized["serial"].get("port") or "").strip()
    normalized["serial"]["device_key_mode"] = (
        str(normalized["serial"].get("device_key_mode") or "pcd_first").strip() or "pcd_first"
    )
    normalized["serial"]["replay_file_path"] = str(
        normalized["serial"].get("replay_file_path") or ""
    ).strip()
    normalized["serial"]["replay_interval_seconds"] = max(
        1,
        int(normalized["serial"].get("replay_interval_seconds") or 60),
    )

    return normalized


def _normalize_string(value, default=""):
    return str(value if value is not None else default)


def _normalize_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def normalize_accounting_settings(settings):
    raw_accounting = settings.get("accounting")
    normalized_accounting = copy.deepcopy(DEFAULT_ACCOUNTING_SETTINGS)

    if not isinstance(raw_accounting, dict):
        settings["accounting"] = normalized_accounting
        return True

    def parse_int(value, fallback, minimum=None, maximum=None):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = fallback
        if minimum is not None:
            parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    def parse_float(value, fallback, minimum=None, maximum=None):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = fallback
        if minimum is not None:
            parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    normalized_accounting["enabled"] = _normalize_bool(
        raw_accounting.get("enabled"),
        default=DEFAULT_ACCOUNTING_SETTINGS["enabled"],
    )
    normalized_accounting["business_type"] = (
        _normalize_string(
            raw_accounting.get("business_type"),
            DEFAULT_ACCOUNTING_SETTINGS["business_type"],
        ).strip()
        or DEFAULT_ACCOUNTING_SETTINGS["business_type"]
    )
    normalized_accounting["base_currency"] = (
        _normalize_string(
            raw_accounting.get("base_currency"),
            DEFAULT_ACCOUNTING_SETTINGS["base_currency"],
        ).strip()
        or DEFAULT_ACCOUNTING_SETTINGS["base_currency"]
    ).upper()
    normalized_accounting["reporting_basis"] = str(
        raw_accounting.get("reporting_basis")
        or DEFAULT_ACCOUNTING_SETTINGS["reporting_basis"]
    ).strip().lower()
    if normalized_accounting["reporting_basis"] not in {"accrual", "cash"}:
        normalized_accounting["reporting_basis"] = DEFAULT_ACCOUNTING_SETTINGS["reporting_basis"]
    normalized_accounting["fiscal_year_start_month"] = parse_int(
        raw_accounting.get("fiscal_year_start_month"),
        DEFAULT_ACCOUNTING_SETTINGS["fiscal_year_start_month"],
        minimum=1,
        maximum=12,
    )
    normalized_accounting["default_credit_term_days"] = parse_int(
        raw_accounting.get("default_credit_term_days"),
        DEFAULT_ACCOUNTING_SETTINGS["default_credit_term_days"],
        minimum=0,
        maximum=3650,
    )
    normalized_accounting["tax_rate"] = parse_float(
        raw_accounting.get("tax_rate"),
        DEFAULT_ACCOUNTING_SETTINGS["tax_rate"],
        minimum=0,
        maximum=100,
    )
    normalized_accounting["tax_mode"] = str(
        raw_accounting.get("tax_mode") or DEFAULT_ACCOUNTING_SETTINGS["tax_mode"]
    ).strip().lower()
    if normalized_accounting["tax_mode"] not in {"vat", "inclusive", "exclusive", "multi_rate"}:
        normalized_accounting["tax_mode"] = DEFAULT_ACCOUNTING_SETTINGS["tax_mode"]
    normalized_accounting["lock_date"] = _normalize_string(
        raw_accounting.get("lock_date"),
        DEFAULT_ACCOUNTING_SETTINGS["lock_date"],
    ).strip()

    raw_modules = raw_accounting.get("modules") if isinstance(raw_accounting.get("modules"), dict) else {}
    for module_key, default_module in DEFAULT_ACCOUNTING_SETTINGS["modules"].items():
        raw_module = raw_modules.get(module_key)
        if not isinstance(raw_module, dict):
            continue
        for option_key, default_value in default_module.items():
            normalized_accounting["modules"][module_key][option_key] = _normalize_bool(
                raw_module.get(option_key),
                default=default_value,
            )

    updated = raw_accounting != normalized_accounting
    settings["accounting"] = normalized_accounting
    return updated


def normalize_role_name(role_name, default="guest"):
    normalized = str(role_name or "").strip().lower()
    normalized = "".join(character for character in normalized if character.isalnum() or character in {"_", "-"})
    return normalized or default


def normalize_role_permissions(settings):
    raw_permissions = settings.get("role_permissions")
    normalized_permissions = {}
    updated = False
    page_keys = tuple(DEFAULT_ROLE_PERMISSIONS["admin"].keys())

    if not isinstance(raw_permissions, dict):
        raw_permissions = {}
        updated = True

    for role_name, page_permissions in raw_permissions.items():
        normalized_role = normalize_role_name(role_name, default="")
        if not normalized_role:
            updated = True
            continue
        normalized_page_permissions = {}
        for page_key in page_keys:
            normalized_page_permissions[page_key] = _normalize_bool(
                page_permissions.get(page_key) if isinstance(page_permissions, dict) else None,
                default=DEFAULT_ROLE_PERMISSIONS.get(normalized_role, {}).get(page_key, False),
            )
        normalized_permissions[normalized_role] = normalized_page_permissions
        if normalized_role != role_name or not isinstance(page_permissions, dict):
            updated = True

    for role_name, default_permissions in DEFAULT_ROLE_PERMISSIONS.items():
        existing_permissions = normalized_permissions.get(role_name)
        if not isinstance(existing_permissions, dict):
            normalized_permissions[role_name] = copy.deepcopy(default_permissions)
            updated = True
            continue
        for page_key, enabled in default_permissions.items():
            if page_key not in existing_permissions:
                existing_permissions[page_key] = enabled
                updated = True

    if normalized_permissions.get("admin") != DEFAULT_ROLE_PERMISSIONS["admin"]:
        normalized_permissions["admin"] = copy.deepcopy(DEFAULT_ROLE_PERMISSIONS["admin"])
        updated = True

    settings["role_permissions"] = normalized_permissions
    return updated


def _normalize_endpoint_api_auth_type(api_config):
    auth_type = str(api_config.get("auth_type") or "").strip().lower()
    valid_auth_types = {
        "none",
        "bearer_token",
        "bearer_login",
        "basic",
        "api_key_header",
        "api_key_query",
        "custom_headers",
    }
    if auth_type in valid_auth_types:
        return auth_type
    if str(api_config.get("token_url") or "").strip():
        return "bearer_login"
    return "none"


def _legacy_endpoint_api_requests(api_config):
    requests = []

    organizations_path = str(
        api_config.get("organizations_path")
        or DEFAULT_ENDPOINT_API["requests"][0]["path"]
    ).strip()
    if organizations_path:
        requests.append(
            {
                "id": "organizations",
                "role": "organizations",
                "name": "Organizations",
                "method": "GET",
                "path": organizations_path,
                "params": [],
                "body": "",
                "use_auth": True,
                "max_round_times": 0,
                "max_interval_minutes": 0,
                "interval_unlimited": True,
                "run_every_times": 0,
                "run_interval_minutes": 0,
            }
        )

    devices_path = str(
        api_config.get("devices_path")
        or DEFAULT_ENDPOINT_API["requests"][1]["path"]
    ).strip()
    devices_org_param = str(api_config.get("devices_org_param") or "org_uuid").strip()
    if devices_path:
        requests.append(
            {
                "id": "devices",
                "role": "devices",
                "name": "Devices",
                "method": "GET",
                "path": devices_path,
                "params": (
                    [{"key": devices_org_param, "value": "{{organization_uuid}}"}]
                    if devices_org_param
                    else []
                ),
                "body": "",
                "use_auth": True,
                "max_round_times": 0,
                "max_interval_minutes": 0,
                "interval_unlimited": True,
                "run_every_times": 0,
                "run_interval_minutes": 0,
            }
        )

    latest_values_path = str(
        api_config.get("latest_values_path")
        or DEFAULT_ENDPOINT_API["requests"][2]["path"]
    ).strip()
    latest_values_device_param = str(
        api_config.get("latest_values_device_param") or "device_uuid"
    ).strip()
    if latest_values_path:
        requests.append(
            {
                "id": "latest_values",
                "role": "latest_values",
                "name": "Latest Values",
                "method": "GET",
                "path": latest_values_path,
                "params": (
                    [{"key": latest_values_device_param, "values": ["{{device_uuid}}"]}]
                    if latest_values_device_param
                    else []
                ),
                "body": "",
                "use_auth": True,
                "max_round_times": 0,
                "max_interval_minutes": 0,
                "interval_unlimited": True,
                "run_every_times": 0,
                "run_interval_minutes": 0,
            }
        )

    return requests or copy.deepcopy(DEFAULT_ENDPOINT_API["requests"])


def _default_endpoint_api_request(role, index=0):
    defaults = {
        request_definition["role"]: copy.deepcopy(request_definition)
        for request_definition in DEFAULT_ENDPOINT_API["requests"]
    }
    request = defaults.get(role, {})
    if request:
        request["id"] = request.get("id") or f"{role}_{index + 1}"
        return request
    return {
        "id": f"request_{index + 1}",
        "role": "custom",
        "name": f"Request {index + 1}",
        "method": "GET",
        "path": "",
        "params": [],
        "body": "",
        "use_auth": True,
        "max_round_times": 0,
        "max_interval_minutes": 0,
        "interval_unlimited": True,
        "run_every_times": 0,
        "run_interval_minutes": 0,
    }


def _normalize_endpoint_api_request_params(params):
    normalized_params = []
    if not isinstance(params, list):
        return normalized_params

    for item in params:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("name") or "").strip()
        raw_values = item.get("values")
        if isinstance(raw_values, list):
            values = [_normalize_string(value) for value in raw_values]
        elif raw_values not in (None, ""):
            values = [_normalize_string(raw_values)]
        else:
            values = [_normalize_string(item.get("value") or "")]
        values = [value for value in values if value != ""]
        if not key and not values:
            continue
        normalized_entry = {"key": key, "values": values}
        if values:
            normalized_entry["value"] = values[0]
        normalized_params.append(normalized_entry)
    return normalized_params


def normalize_endpoint_api_request_definition(request_definition, index=0):
    if not isinstance(request_definition, dict):
        return _default_endpoint_api_request("custom", index)

    role = str(request_definition.get("role") or "").strip().lower()
    if role not in {"organizations", "devices", "latest_values", "history", "history_export", "custom"}:
        role = "custom"
    normalized = _default_endpoint_api_request(role, index)

    normalized["id"] = str(
        request_definition.get("id") or normalized.get("id") or f"{role}_{index + 1}"
    ).strip()
    normalized["name"] = str(
        request_definition.get("name") or normalized.get("name") or f"Request {index + 1}"
    ).strip()
    method = str(request_definition.get("method") or normalized.get("method") or "GET").strip().upper()
    normalized["method"] = method if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} else "GET"
    normalized["path"] = str(request_definition.get("path") or normalized.get("path") or "").strip()
    normalized["params"] = _normalize_endpoint_api_request_params(request_definition.get("params"))
    normalized["body"] = _normalize_string(request_definition.get("body") or "").strip()
    normalized["use_auth"] = _normalize_bool(
        request_definition.get("use_auth"),
        default=normalized.get("use_auth", True),
    )
    try:
        max_round_times = int(
            request_definition.get("max_round_times")
            or request_definition.get("max_interval_minutes")
            or 0
        )
    except (TypeError, ValueError):
        max_round_times = 0
    max_round_times = max(0, max_round_times)
    normalized["max_round_times"] = max_round_times
    normalized["max_interval_minutes"] = max_round_times
    normalized["interval_unlimited"] = _normalize_bool(
        request_definition.get("interval_unlimited"),
        default=normalized.get("interval_unlimited", True),
    )
    try:
        run_every_times = int(
            request_definition.get("run_every_times")
            or request_definition.get("run_interval_minutes")
            or 0
        )
    except (TypeError, ValueError):
        run_every_times = 0
    run_every_times = max(0, run_every_times)
    normalized["run_every_times"] = run_every_times
    normalized["run_interval_minutes"] = run_every_times
    return normalized


def normalize_endpoint_api_definition(api_config):
    normalized = copy.deepcopy(DEFAULT_ENDPOINT_API)
    if not isinstance(api_config, dict):
        return normalized

    for key, value in api_config.items():
        if key == "requests":
            continue
        normalized[key] = value

    normalized["template_id"] = str(normalized.get("template_id") or "").strip()
    normalized["request_headers"] = _normalize_string(normalized.get("request_headers") or "{}").strip() or "{}"
    normalized["auth_type"] = _normalize_endpoint_api_auth_type(normalized)
    normalized["token_url"] = str(normalized.get("token_url") or "").strip()
    normalized["token_method"] = str(normalized.get("token_method") or "POST").strip().upper()
    if normalized["token_method"] not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        normalized["token_method"] = "POST"
    normalized["token_field"] = str(normalized.get("token_field") or "access_token").strip() or "access_token"
    normalized["auth_username"] = str(normalized.get("auth_username") or "").strip()
    normalized["auth_password"] = _normalize_string(normalized.get("auth_password") or "")
    normalized["auth_headers"] = _normalize_string(normalized.get("auth_headers") or "{}").strip() or "{}"
    normalized["auth_body"] = _normalize_string(normalized.get("auth_body") or "")
    normalized["api_key_name"] = str(normalized.get("api_key_name") or "").strip()
    normalized["api_key_value"] = _normalize_string(normalized.get("api_key_value") or "").strip()
    normalized["custom_auth_headers"] = _normalize_string(
        normalized.get("custom_auth_headers") or "{}"
    ).strip() or "{}"

    request_definitions = api_config.get("requests")
    if not isinstance(request_definitions, list) or not request_definitions:
        request_definitions = _legacy_endpoint_api_requests(api_config)

    normalized["requests"] = [
        normalize_endpoint_api_request_definition(request_definition, index)
        for index, request_definition in enumerate(request_definitions)
        if isinstance(request_definition, dict)
    ]
    if not normalized["requests"]:
        normalized["requests"] = copy.deepcopy(DEFAULT_ENDPOINT_API["requests"])
    else:
        existing_ids = {r.get("id") for r in normalized["requests"]}
        for default_req in DEFAULT_ENDPOINT_API["requests"]:
            if default_req.get("id") not in existing_ids:
                normalized["requests"].append(copy.deepcopy(default_req))

    return normalized


def normalize_endpoint_sources(settings):
    sources = settings.get("endpoint_sources")
    if not isinstance(sources, list):
        settings["endpoint_sources"] = [copy.deepcopy(DEFAULT_ENDPOINT_SOURCE)]
        return True

    normalized_sources = []
    for source in sources:
        normalized = normalize_endpoint_source_definition(source)
        if str(normalized.get("name") or "").strip():
            normalized_sources.append(normalized)

    if not normalized_sources:
        normalized_sources = [copy.deepcopy(DEFAULT_ENDPOINT_SOURCE)]

    if sources != normalized_sources:
        settings["endpoint_sources"] = normalized_sources
        return True
    return False


def normalize_endpoint_api_templates(settings):
    templates = settings.get("endpoint_api_templates")
    if not isinstance(templates, list):
        settings["endpoint_api_templates"] = []
        return True

    normalized_templates = []
    updated = False
    for template in templates:
        if not isinstance(template, dict):
            updated = True
            continue
        normalized = {
            "id": str(template.get("id") or "").strip(),
            "name": str(template.get("name") or "").strip(),
            "source": str(template.get("source") or "").strip(),
            "imported_at": str(template.get("imported_at") or "").strip(),
            "base_url": str(template.get("base_url") or "").strip(),
            "variables": template.get("variables") if isinstance(template.get("variables"), dict) else {},
            "requests": template.get("requests") if isinstance(template.get("requests"), list) else [],
            "suggested": template.get("suggested") if isinstance(template.get("suggested"), dict) else {},
        }
        if not normalized["id"] or not normalized["name"]:
            updated = True
            continue
        if template != normalized:
            updated = True
        normalized_templates.append(normalized)

    if updated or templates != normalized_templates:
        settings["endpoint_api_templates"] = normalized_templates
        return True
    return False


def normalize_endpoint_token_store(settings):
    token_store = settings.get("endpoint_token_store")
    if not isinstance(token_store, dict):
        settings["endpoint_token_store"] = {}
        return True

    normalized_store = {}
    updated = False
    for key, value in token_store.items():
        cache_key = str(key or "").strip()
        if not cache_key or not isinstance(value, dict):
            updated = True
            continue
        normalized_entry = {}
        token = str(value.get("token") or "").strip()
        updated_at = str(value.get("updated_at") or "").strip()
        source_names = value.get("source_names")
        if token:
            normalized_entry["token"] = token
        if updated_at:
            normalized_entry["updated_at"] = updated_at
        if isinstance(source_names, list):
            normalized_entry["source_names"] = [
                str(item).strip() for item in source_names if str(item).strip()
            ]
        if value != normalized_entry:
            updated = True
        normalized_store[cache_key] = normalized_entry

    if updated or token_store != normalized_store:
        settings["endpoint_token_store"] = normalized_store
        return True
    return False


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
        "psychrometric_chart",
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
