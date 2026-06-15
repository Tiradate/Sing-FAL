import copy
import os
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    serial = None
    list_ports = None


DEFAULT_BAUDRATE = 9600
DEFAULT_READ_TIMEOUT_MS = 1000
DEFAULT_PREVIEW_LINE_LIMIT = 100
DEFAULT_PARSED_RECORD_LIMIT = 50
DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_REPLAY_INTERVAL_SECONDS = 60

SERIAL_FIELD_LABELS = {
    "record_type": "Record Type",
    "record_ts": "Record Time",
    "record_date": "Record Date",
    "device_p": "Device P",
    "device_c": "Device C",
    "device_d": "Device D",
    "device_key": "Device Key",
    "headline_text": "Headline",
    "detail_text": "Detail",
    "raw_line_1": "Raw Line 1",
    "raw_line_2": "Raw Line 2",
    "raw_line_3": "Raw Line 3",
    "command_text": "Command Text",
    "command_source_p": "Command Source P",
    "command_source_c": "Command Source C",
    "command_source_d": "Command Source D",
    "target_p": "Target P",
    "target_c": "Target C",
    "target_d": "Target D",
    "event_text": "Event Text",
    "event_description": "Event Description",
}

_PCD_PATTERN = re.compile(
    r"P:(?P<p>\S+)\s+C:(?P<c>\S+)\s+D:(?P<d>\S+)",
    re.IGNORECASE,
)
_OPERATOR_PATTERN = re.compile(
    r"^-?(?P<headline>OPERATOR COMMAND)-?\s+"
    r"(?P<record_ts>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<record_date>\d{2}/\d{2}/\d{4})\s+"
    r"P:(?P<src_p>\S+)\s+C:(?P<src_c>\S+)\s+D:(?P<src_d>\S+)"
    r"(?:\s+(?P<tail>.*))?$",
    re.IGNORECASE,
)
_EVENT_PATTERN = re.compile(
    r"^(?P<event_text>.+?)\s*::\s+"
    r"(?P<record_ts>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<record_date>\d{2}/\d{2}/\d{4})\s+"
    r"P:(?P<p>\S+)\s+C:(?P<c>\S+)\s+D:(?P<d>\S+)\s*$",
    re.IGNORECASE,
)


def dependency_available():
    return serial is not None and list_ports is not None


def list_available_ports():
    if not dependency_available():
        raise RuntimeError("pyserial is not installed")

    ports = []
    for port_info in list_ports.comports():
        path = str(getattr(port_info, "device", "") or "").strip()
        if not path:
            continue
        description = str(getattr(port_info, "description", "") or "").strip()
        hwid = str(getattr(port_info, "hwid", "") or "").strip()
        label_parts = [path]
        if description and description.lower() != "n/a":
            label_parts.append(description)
        ports.append(
            {
                "path": path,
                "label": " - ".join(label_parts),
                "description": description,
                "hwid": hwid,
            }
        )
    return sorted(ports, key=lambda item: item["path"].lower())


def _normalize_replay_state(replay_state):
    replay = replay_state if isinstance(replay_state, dict) else {}
    try:
        interval_seconds = int(
            replay.get("interval_seconds") or DEFAULT_REPLAY_INTERVAL_SECONDS
        )
    except (TypeError, ValueError):
        interval_seconds = DEFAULT_REPLAY_INTERVAL_SECONDS
    try:
        next_batch_index = int(replay.get("next_batch_index") or 0)
    except (TypeError, ValueError):
        next_batch_index = 0
    try:
        total_batches = int(replay.get("total_batches") or 0)
    except (TypeError, ValueError):
        total_batches = 0
    try:
        next_run_at = float(replay.get("next_run_at") or 0.0)
    except (TypeError, ValueError):
        next_run_at = 0.0
    try:
        last_batch_index = int(replay.get("last_batch_index") or 0)
    except (TypeError, ValueError):
        last_batch_index = 0

    return {
        "active": bool(replay.get("active")),
        "file_path": str(replay.get("file_path") or "").strip(),
        "interval_seconds": max(1, interval_seconds),
        "next_batch_index": max(0, next_batch_index),
        "total_batches": max(0, total_batches),
        "next_run_at": max(0.0, next_run_at),
        "started_at": str(replay.get("started_at") or "").strip(),
        "last_batch_at": str(replay.get("last_batch_at") or "").strip(),
        "last_batch_index": max(0, last_batch_index),
        "completed_at": str(replay.get("completed_at") or "").strip(),
        "stopped_at": str(replay.get("stopped_at") or "").strip(),
        "last_error": str(replay.get("last_error") or "").strip(),
    }


def normalize_state(execution_state):
    state = execution_state if isinstance(execution_state, dict) else {}
    latest_values = state.get("latest_values")
    if not isinstance(latest_values, dict):
        latest_values = {"items": []}
    if not isinstance(latest_values.get("items"), list):
        latest_values["items"] = []
    device_items = state.get("device_items")
    if not isinstance(device_items, list):
        device_items = []
    parsed_records = state.get("parsed_records")
    if not isinstance(parsed_records, list):
        parsed_records = []
    raw_lines = state.get("raw_lines")
    if not isinstance(raw_lines, list):
        raw_lines = []
    partial_record = state.get("partial_record")
    if not isinstance(partial_record, list):
        partial_record = []
    record_counts = state.get("record_counts_by_type")
    normalized_counts = {}
    if isinstance(record_counts, dict):
        for key, value in record_counts.items():
            key_text = str(key or "").strip()
            if not key_text:
                continue
            try:
                normalized_counts[key_text] = max(0, int(value or 0))
            except (TypeError, ValueError):
                continue

    return {
        "raw_lines": [str(item) for item in raw_lines][-DEFAULT_PREVIEW_LINE_LIMIT:],
        "partial_record": [str(item) for item in partial_record if str(item).strip()],
        "parsed_records": [
            item for item in parsed_records if isinstance(item, dict)
        ][-DEFAULT_PARSED_RECORD_LIMIT:],
        "latest_values": latest_values,
        "device_items": [item for item in device_items if isinstance(item, dict)],
        "record_counts_by_type": normalized_counts,
        "last_error": str(state.get("last_error") or "").strip(),
        "last_read_at": str(state.get("last_read_at") or "").strip(),
        "live_source_paused": bool(state.get("live_source_paused")),
        "replay": _normalize_replay_state(state.get("replay")),
    }


def get_replay_status(execution_state):
    return normalize_state(execution_state).get("replay", {})


def is_live_source_paused(execution_state):
    return bool(normalize_state(execution_state).get("live_source_paused"))


def apply_replay_action(execution_state, serial_config, action):
    state = normalize_state(execution_state)
    action_name = str(action or "").strip().lower()
    if not action_name:
        return state

    normalized_config = normalize_serial_config(serial_config)
    replay = state["replay"]
    file_path = (
        str(normalized_config.get("replay_file_path") or replay.get("file_path") or "")
        .strip()
    )
    interval_seconds = max(
        1,
        int(
            replay.get("interval_seconds")
            or normalized_config.get("replay_interval_seconds")
            or DEFAULT_REPLAY_INTERVAL_SECONDS
        ),
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    if action_name == "start":
        if not file_path:
            raise ValueError("Serial replay file path is required")
        batches = _load_replay_batches(file_path)
        if not batches:
            raise ValueError("Serial replay file did not contain any record batches")
        state["live_source_paused"] = True
        replay.update(
            {
                "active": True,
                "file_path": file_path,
                "interval_seconds": interval_seconds,
                "next_batch_index": 0,
                "total_batches": len(batches),
                "next_run_at": 0.0,
                "started_at": now_iso,
                "last_batch_at": "",
                "last_batch_index": 0,
                "completed_at": "",
                "stopped_at": "",
                "last_error": "",
            }
        )
        return state

    if action_name == "stop":
        state["live_source_paused"] = True
        replay.update(
            {
                "active": False,
                "next_run_at": 0.0,
                "stopped_at": now_iso,
                "last_error": "",
            }
        )
        return state

    if action_name == "resume_source":
        state["live_source_paused"] = False
        replay.update(
            {
                "active": False,
                "next_run_at": 0.0,
                "stopped_at": now_iso,
                "last_error": "",
            }
        )
        return state

    raise ValueError(f"Unsupported serial replay action: {action_name}")


def build_preview_payload(
    source_name,
    serial_config,
    execution_state=None,
    timezone_name="Asia/Bangkok",
    read_from_source=True,
):
    state = normalize_state(execution_state)
    starting_record_total = _get_record_total(state)
    next_input_state, raw_lines = _read_source_lines(
        state,
        serial_config,
        read_from_source=read_from_source,
    )
    next_state = apply_stream_lines(
        next_input_state,
        raw_lines,
        source_name=source_name,
        timezone_name=timezone_name,
    )
    new_record_count = max(0, _get_record_total(next_state) - starting_record_total)
    return {
        "raw_lines": next_state["raw_lines"],
        "parsed_records": next_state["parsed_records"],
        "devices": next_state["device_items"],
        "device_items": next_state["device_items"],
        "ready_device_items": build_ready_device_items(
            next_state["device_items"],
            next_state["latest_values"],
        ),
        "latest_values": next_state["latest_values"],
        "execution_state": next_state,
        "should_ingest": new_record_count > 0,
        "new_record_count": new_record_count,
        "serial_debug": {
            "partial_record": next_state["partial_record"],
            "record_counts_by_type": next_state["record_counts_by_type"],
            "last_error": next_state["last_error"],
            "last_read_at": next_state["last_read_at"],
            "replay": next_state["replay"],
            "new_record_count": new_record_count,
        },
    }


def _get_record_total(state):
    return sum(
        max(0, int(value or 0))
        for value in normalize_state(state).get("record_counts_by_type", {}).values()
    )


def _read_source_lines(execution_state, serial_config, read_from_source=True):
    state = normalize_state(execution_state)
    if not read_from_source:
        return state, []

    replay_state = state.get("replay", {})
    if replay_state.get("active"):
        return _read_replay_lines(state, serial_config)
    if state.get("live_source_paused"):
        return state, []

    raw_lines = read_serial_lines(serial_config)
    return state, raw_lines


def _read_replay_lines(execution_state, serial_config):
    state = normalize_state(execution_state)
    normalized_config = normalize_serial_config(serial_config)
    replay = state["replay"]
    file_path = (
        str(replay.get("file_path") or normalized_config.get("replay_file_path") or "").strip()
    )
    if not file_path:
        replay.update(
            {
                "active": False,
                "next_run_at": 0.0,
                "last_error": "Serial replay file path is required",
            }
        )
        state["last_error"] = replay["last_error"]
        return state, []

    try:
        batches = _load_replay_batches(file_path)
    except Exception as exc:
        replay.update(
            {
                "active": False,
                "next_run_at": 0.0,
                "last_error": str(exc),
            }
        )
        state["last_error"] = replay["last_error"]
        return state, []

    replay["file_path"] = file_path
    replay["interval_seconds"] = max(
        1,
        int(
            replay.get("interval_seconds")
            or normalized_config.get("replay_interval_seconds")
            or DEFAULT_REPLAY_INTERVAL_SECONDS
        ),
    )
    replay["total_batches"] = len(batches)
    state["last_error"] = ""

    if not batches:
        replay.update(
            {
                "active": False,
                "next_run_at": 0.0,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "last_error": "",
            }
        )
        return state, []

    next_batch_index = min(replay.get("next_batch_index", 0), len(batches))
    if next_batch_index >= len(batches):
        if not replay.get("completed_at"):
            replay["completed_at"] = datetime.now(timezone.utc).isoformat()
        replay["active"] = False
        replay["next_run_at"] = 0.0
        return state, []

    now = time.time()
    next_run_at = float(replay.get("next_run_at") or 0.0)
    if next_run_at > now:
        return state, []

    batch_lines = list(batches[next_batch_index])
    emitted_at = datetime.now(timezone.utc).isoformat()
    replay["last_batch_at"] = emitted_at
    replay["last_batch_index"] = next_batch_index + 1
    replay["next_batch_index"] = next_batch_index + 1
    replay["stopped_at"] = ""
    replay["last_error"] = ""

    if replay["next_batch_index"] >= len(batches):
        replay["active"] = False
        replay["next_run_at"] = 0.0
        replay["completed_at"] = emitted_at
    else:
        replay["active"] = True
        replay["completed_at"] = ""
        replay["next_run_at"] = now + replay["interval_seconds"]

    return state, [*batch_lines, ""]


def _load_replay_batches(file_path):
    normalized_path = str(file_path or "").strip()
    if not normalized_path:
        raise ValueError("Serial replay file path is required")
    if not os.path.isfile(normalized_path):
        raise ValueError(f"Serial replay file was not found: {normalized_path}")

    with open(normalized_path, "r", encoding="utf-8", errors="replace") as replay_file:
        raw_text = replay_file.read()

    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    batches = []
    current_batch = []
    for raw_line in lines:
        line = str(raw_line or "")
        if not line.strip():
            if current_batch:
                batches.append(current_batch)
                current_batch = []
            continue
        current_batch.append(line)

    if current_batch:
        batches.append(current_batch)

    return batches


def apply_stream_lines(execution_state, raw_lines, source_name="", timezone_name="Asia/Bangkok"):
    state = normalize_state(execution_state)
    next_state = copy.deepcopy(state)
    next_state["last_error"] = str(state.get("last_error") or "").strip()
    next_state["last_read_at"] = datetime.now(timezone.utc).isoformat()
    for raw_line in raw_lines:
        line = str(raw_line).replace("\r", "")
        next_state["raw_lines"].append(line)
        next_state["raw_lines"] = next_state["raw_lines"][-DEFAULT_PREVIEW_LINE_LIMIT:]
        if not line.strip():
            if next_state["partial_record"]:
                parsed_record = parse_record(
                    next_state["partial_record"],
                    timezone_name=timezone_name,
                )
                if parsed_record:
                    _append_parsed_record(next_state, parsed_record)
                next_state["partial_record"] = []
            continue
        next_state["partial_record"].append(line)

    _refresh_device_state(next_state, source_name=source_name)
    return next_state


def parse_serial_text(text, source_name="Serial", timezone_name="Asia/Bangkok"):
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return apply_stream_lines({}, lines, source_name=source_name, timezone_name=timezone_name)


def read_serial_lines(serial_config):
    if not dependency_available():
        raise RuntimeError("pyserial is not installed")

    normalized_config = normalize_serial_config(serial_config)
    port = normalized_config["port"]
    if not port:
        raise ValueError("Serial port is required")

    timeout_seconds = max(0.1, normalized_config["read_timeout_ms"] / 1000.0)
    line_limit = normalized_config["preview_line_limit"]
    lines = []
    deadline = time.monotonic() + timeout_seconds
    read_timeout = min(timeout_seconds, 0.25)

    try:
        with serial.Serial(
            port=port,
            baudrate=normalized_config["baudrate"],
            timeout=read_timeout,
        ) as connection:
            idle_reads = 0
            while time.monotonic() < deadline and len(lines) < line_limit:
                raw = connection.readline()
                if not raw:
                    idle_reads += 1
                    if idle_reads >= 2:
                        break
                    continue
                idle_reads = 0
                lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
    except Exception as exc:  # pragma: no cover - depends on host serial devices
        raise RuntimeError(f"Unable to read serial port '{port}': {exc}") from exc

    return lines


def normalize_serial_config(config):
    raw_config = config if isinstance(config, dict) else {}
    try:
        baudrate = int(raw_config.get("baudrate") or DEFAULT_BAUDRATE)
    except (TypeError, ValueError):
        baudrate = DEFAULT_BAUDRATE
    try:
        read_timeout_ms = int(raw_config.get("read_timeout_ms") or DEFAULT_READ_TIMEOUT_MS)
    except (TypeError, ValueError):
        read_timeout_ms = DEFAULT_READ_TIMEOUT_MS
    try:
        preview_line_limit = int(raw_config.get("preview_line_limit") or DEFAULT_PREVIEW_LINE_LIMIT)
    except (TypeError, ValueError):
        preview_line_limit = DEFAULT_PREVIEW_LINE_LIMIT
    try:
        replay_interval_seconds = int(
            raw_config.get("replay_interval_seconds") or DEFAULT_REPLAY_INTERVAL_SECONDS
        )
    except (TypeError, ValueError):
        replay_interval_seconds = DEFAULT_REPLAY_INTERVAL_SECONDS
    return {
        "port": str(raw_config.get("port") or "").strip(),
        "baudrate": max(1, baudrate),
        "read_timeout_ms": max(100, read_timeout_ms),
        "preview_line_limit": max(10, min(500, preview_line_limit)),
        "device_key_mode": str(raw_config.get("device_key_mode") or "pcd_first").strip() or "pcd_first",
        "replay_file_path": str(raw_config.get("replay_file_path") or "").strip(),
        "replay_interval_seconds": max(1, replay_interval_seconds),
    }


def build_ready_device_items(device_items, latest_values):
    latest_items = latest_values.get("items") if isinstance(latest_values, dict) else []
    latest_items = latest_items if isinstance(latest_items, list) else []
    latest_map = {}
    for item in latest_items:
        if not isinstance(item, dict):
            continue
        device_key = str(item.get("device_uuid") or item.get("device_id") or "").strip()
        if device_key:
            latest_map[device_key] = item

    ready_device_items = []
    for device in device_items:
        device_key = str(
            device.get("uuid")
            or device.get("device_uuid")
            or device.get("device_id")
            or device.get("id")
            or ""
        ).strip()
        if not device_key or device_key not in latest_map:
            continue
        enriched = dict(device)
        enriched["latest_values"] = latest_map[device_key]
        ready_device_items.append(enriched)
    return ready_device_items


def _append_parsed_record(state, parsed_record):
    state["parsed_records"].append(parsed_record)
    state["parsed_records"] = state["parsed_records"][-DEFAULT_PARSED_RECORD_LIMIT:]
    record_type = str(parsed_record.get("record_type") or "unknown").strip() or "unknown"
    state["record_counts_by_type"][record_type] = int(
        state["record_counts_by_type"].get(record_type, 0) or 0
    ) + 1


def _refresh_device_state(state, source_name=""):
    latest_map = {}
    for item in state["latest_values"].get("items", []):
        if not isinstance(item, dict):
            continue
        device_key = str(item.get("device_uuid") or item.get("device_id") or "").strip()
        if device_key:
            latest_map[device_key] = item

    device_map = {}
    for device in state["device_items"]:
        if not isinstance(device, dict):
            continue
        device_key = str(
            device.get("uuid")
            or device.get("device_uuid")
            or device.get("device_id")
            or device.get("id")
            or ""
        ).strip()
        if device_key:
            device_map[device_key] = dict(device)

    for parsed_record in state["parsed_records"]:
        device_key = str(parsed_record.get("device_key") or "").strip()
        if not device_key:
            continue
        latest_map[device_key] = _build_latest_value_item(parsed_record)
        device_map[device_key] = _build_device_item(parsed_record, source_name=source_name)

    sorted_device_keys = sorted(device_map, key=lambda item: device_map[item].get("display_name", item).lower())
    state["device_items"] = [device_map[key] for key in sorted_device_keys]
    state["latest_values"] = {"items": [latest_map[key] for key in sorted(latest_map)]}


def _build_latest_value_item(parsed_record):
    fields = parsed_record.get("fields", {})
    timestamp_iso = str(parsed_record.get("timestamp") or datetime.now(timezone.utc).isoformat())
    device_key = str(parsed_record.get("device_key") or "").strip()
    display_name = str(parsed_record.get("display_name") or device_key).strip() or device_key
    values = []
    for key, value in fields.items():
        if value in (None, ""):
            continue
        values.append(
            {
                "field": key,
                "value": value,
                "ts": timestamp_iso,
            }
        )
    return {
        "device_uuid": device_key,
        "uuid": device_key,
        "device_id": device_key,
        "display_name": display_name,
        "name": display_name,
        "device": {
            "uuid": device_key,
            "display_name": display_name,
            "name": display_name,
        },
        "ts": timestamp_iso,
        "values": values,
    }


def _build_device_item(parsed_record, source_name=""):
    device_key = str(parsed_record.get("device_key") or "").strip()
    display_name = str(parsed_record.get("display_name") or device_key).strip() or device_key
    fields = parsed_record.get("fields", {})
    return {
        "uuid": device_key,
        "device_uuid": device_key,
        "device_id": device_key,
        "id": device_key,
        "name": display_name,
        "device_name": display_name,
        "display_name": display_name,
        "label": display_name,
        "source_name": str(source_name or "").strip(),
        "record_type": fields.get("record_type") or "",
        "headline_text": fields.get("headline_text") or "",
        "detail_text": fields.get("detail_text") or "",
    }


def parse_record(lines, timezone_name="Asia/Bangkok"):
    normalized_lines = [str(line).strip() for line in lines if str(line).strip()]
    if not normalized_lines:
        return None
    first_line = normalized_lines[0]
    if first_line.startswith("-"):
        return _parse_operator_record(normalized_lines, timezone_name=timezone_name)
    if "::" in first_line:
        return _parse_event_record(normalized_lines, timezone_name=timezone_name)
    return _parse_unknown_record(normalized_lines, timezone_name=timezone_name)


def _parse_operator_record(lines, timezone_name="Asia/Bangkok"):
    if len(lines) < 3:
        return None
    first_line = lines[0]
    second_line = lines[1]
    third_line = lines[2]
    first_match = _OPERATOR_PATTERN.match(first_line)
    target_match = _PCD_PATTERN.search(third_line)
    if not first_match or not target_match:
        return _parse_unknown_record(lines, timezone_name=timezone_name)

    source_tail = str(first_match.group("tail") or "").strip()
    target_p = str(target_match.group("p") or "").strip()
    target_c = str(target_match.group("c") or "").strip()
    target_d = str(target_match.group("d") or "").strip()
    device_key = _build_device_key(target_p, target_c, target_d)
    timestamp_iso = _build_timestamp_iso(
        first_match.group("record_date"),
        first_match.group("record_ts"),
        timezone_name=timezone_name,
    )
    detail_parts = [part for part in (source_tail, second_line, third_line) if str(part or "").strip()]
    fields = {
        "record_type": "operator_command",
        "record_ts": str(first_match.group("record_ts") or "").strip(),
        "record_date": str(first_match.group("record_date") or "").strip(),
        "device_p": target_p,
        "device_c": target_c,
        "device_d": target_d,
        "device_key": device_key,
        "headline_text": "OPERATOR COMMAND",
        "detail_text": "\n".join(detail_parts),
        "raw_line_1": first_line,
        "raw_line_2": second_line,
        "raw_line_3": third_line,
        "command_text": second_line,
        "command_source_p": str(first_match.group("src_p") or "").strip(),
        "command_source_c": str(first_match.group("src_c") or "").strip(),
        "command_source_d": str(first_match.group("src_d") or "").strip(),
        "target_p": target_p,
        "target_c": target_c,
        "target_d": target_d,
    }
    return {
        "record_type": "operator_command",
        "timestamp": timestamp_iso,
        "device_key": device_key,
        "display_name": _format_display_name(target_p, target_c, target_d),
        "fields": fields,
        "raw_lines": lines[:3],
    }


def _parse_event_record(lines, timezone_name="Asia/Bangkok"):
    if len(lines) < 2:
        return None
    first_line = lines[0]
    second_line = lines[1]
    match = _EVENT_PATTERN.match(first_line)
    if not match:
        return _parse_unknown_record(lines, timezone_name=timezone_name)
    device_p = str(match.group("p") or "").strip()
    device_c = str(match.group("c") or "").strip()
    device_d = str(match.group("d") or "").strip()
    device_key = _build_device_key(device_p, device_c, device_d)
    timestamp_iso = _build_timestamp_iso(
        match.group("record_date"),
        match.group("record_ts"),
        timezone_name=timezone_name,
    )
    event_text = str(match.group("event_text") or "").strip()
    fields = {
        "record_type": "event_status",
        "record_ts": str(match.group("record_ts") or "").strip(),
        "record_date": str(match.group("record_date") or "").strip(),
        "device_p": device_p,
        "device_c": device_c,
        "device_d": device_d,
        "device_key": device_key,
        "headline_text": event_text,
        "detail_text": second_line,
        "raw_line_1": first_line,
        "raw_line_2": second_line,
        "event_text": event_text,
        "event_description": second_line,
    }
    return {
        "record_type": "event_status",
        "timestamp": timestamp_iso,
        "device_key": device_key,
        "display_name": _format_display_name(device_p, device_c, device_d),
        "fields": fields,
        "raw_lines": lines[:2],
    }


def _parse_unknown_record(lines, timezone_name="Asia/Bangkok"):
    del timezone_name
    first_line = lines[0]
    pcd_match = _PCD_PATTERN.search("\n".join(lines))
    if not pcd_match:
        return None
    device_p = str(pcd_match.group("p") or "").strip()
    device_c = str(pcd_match.group("c") or "").strip()
    device_d = str(pcd_match.group("d") or "").strip()
    device_key = _build_device_key(device_p, device_c, device_d)
    fields = {
        "record_type": "unknown",
        "device_p": device_p,
        "device_c": device_c,
        "device_d": device_d,
        "device_key": device_key,
        "headline_text": first_line,
        "detail_text": "\n".join(lines[1:]),
        "raw_line_1": lines[0] if len(lines) > 0 else "",
        "raw_line_2": lines[1] if len(lines) > 1 else "",
        "raw_line_3": lines[2] if len(lines) > 2 else "",
    }
    return {
        "record_type": "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "device_key": device_key,
        "display_name": _format_display_name(device_p, device_c, device_d),
        "fields": fields,
        "raw_lines": lines[:3],
    }


def _format_display_name(device_p, device_c, device_d):
    return f"P:{device_p} C:{device_c} D:{device_d}".strip()


def _build_device_key(device_p, device_c, device_d):
    p_text = str(device_p or "").strip().lower()
    c_text = str(device_c or "").strip().lower()
    d_text = str(device_d or "").strip().lower()
    return f"p{p_text}-c{c_text}-d{d_text}"


def _build_timestamp_iso(record_date, record_ts, timezone_name="Asia/Bangkok"):
    date_text = str(record_date or "").strip()
    time_text = str(record_ts or "").strip()
    if not date_text or not time_text:
        return datetime.now(timezone.utc).isoformat()
    try:
        local_tz = ZoneInfo(str(timezone_name or "Asia/Bangkok"))
    except Exception:
        local_tz = timezone.utc
    try:
        parsed = datetime.strptime(f"{date_text} {time_text}", "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return datetime.now(timezone.utc).isoformat()
    return parsed.replace(tzinfo=local_tz).isoformat()
