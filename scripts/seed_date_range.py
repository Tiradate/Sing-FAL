#!/usr/bin/env python3
import argparse
from datetime import date, datetime, time, timedelta, timezone
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.db import CALENDAR_DB, SENSOR_DB, connect, init_all
from services.data import ingest_milesight_payload


METRICS = {
    "temperature": {"unit": "°C", "base": 24.0, "variance": 3.0},
    "humidity": {"unit": "%RH", "base": 55.0, "variance": 10.0},
    "co2": {"unit": "ppm", "base": 650.0, "variance": 180.0},
    "pm25": {"unit": "µg/m³", "base": 12.0, "variance": 6.0},
    "pm10": {"unit": "µg/m³", "base": 24.0, "variance": 8.0},
    "tvoc": {"unit": "mg/m³", "base": 0.4, "variance": 0.2},
}

FLOORS = ["F1", "F2", "F3"]
ZONES = ["Lobby", "Office", "Meeting", "Pantry", "Hallway", "Storage"]


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must be in YYYY-MM-DD format") from exc


def format_floor_reference(floor_id):
    normalized = floor_id.strip().upper()
    if normalized.startswith("FL"):
        return normalized
    if normalized.startswith("F") and normalized[1:].isdigit():
        return f"FL{normalized[1:]}"
    if normalized.isdigit():
        return f"FL{normalized}"
    return normalized


def generate_devices(count, rng):
    devices = []
    floor_counts = {floor: 0 for floor in FLOORS}
    for index in range(1, count + 1):
        floor = FLOORS[(index - 1) % len(FLOORS)]
        floor_counts[floor] += 1
        floor_ref = format_floor_reference(floor)
        device_id = f"AM30X-{floor_ref}-{floor_counts[floor]:03d}"
        zone = rng.choice(ZONES)
        location_x = rng.uniform(5, 95)
        location_y = rng.uniform(5, 95)
        signal_quality = rng.randint(60, 99)
        devices.append(
            (
                device_id,
                "Milesight AM30x",
                floor,
                zone,
                location_x,
                location_y,
                datetime.now(timezone.utc).isoformat(),
                signal_quality,
            )
        )
    return devices


def build_device_record(
    device_id,
    rng,
    model=None,
    floor_id=None,
    zone=None,
    location_x=None,
    location_y=None,
    last_seen=None,
    signal_quality=None,
):
    resolved_model = model or "Milesight AM30x"
    resolved_floor = floor_id or rng.choice(FLOORS)
    resolved_zone = zone or rng.choice(ZONES)
    resolved_location_x = location_x if location_x is not None else rng.uniform(5, 95)
    resolved_location_y = location_y if location_y is not None else rng.uniform(5, 95)
    resolved_last_seen = last_seen or datetime.now(timezone.utc).isoformat()
    resolved_signal_quality = signal_quality if signal_quality is not None else rng.randint(60, 99)
    return (
        device_id,
        resolved_model,
        resolved_floor,
        resolved_zone,
        resolved_location_x,
        resolved_location_y,
        resolved_last_seen,
        resolved_signal_quality,
    )


def load_devices_from_db(conn, rng, device_ids=None):
    if device_ids:
        placeholders = ", ".join(["?"] * len(device_ids))
        rows = conn.execute(
            f"""
            SELECT device_id, model, floor_id, zone, location_x, location_y, last_seen, signal_quality
            FROM devices
            WHERE device_id IN ({placeholders})
            """,
            device_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT device_id, model, floor_id, zone, location_x, location_y, last_seen, signal_quality
            FROM devices
            """
        ).fetchall()
    devices = []
    existing_ids = set()
    for row in rows:
        device_id = row["device_id"]
        existing_ids.add(device_id)
        devices.append(
            build_device_record(
                device_id=device_id,
                rng=rng,
                model=row["model"],
                floor_id=row["floor_id"],
                zone=row["zone"],
                location_x=row["location_x"],
                location_y=row["location_y"],
                last_seen=row["last_seen"],
                signal_quality=row["signal_quality"],
            )
        )
    return devices, existing_ids


def iter_hourly_timestamps(start_date, end_date):
    current = datetime.combine(start_date, time.min)
    end_ts = datetime.combine(end_date, time.max)
    while current <= end_ts:
        yield current
        current += timedelta(hours=1)


def seed_calendar_summary(start_date, end_date, rng, overwrite):
    with connect(CALENDAR_DB) as conn:
        if overwrite:
            conn.execute("DELETE FROM daily_alarm_summary")
        rows = []
        current = start_date
        while current <= end_date:
            moderate = rng.randint(0, 5)
            unhealthy = rng.randint(0, 4)
            total = moderate + unhealthy
            rows.append((current.isoformat(), total, moderate, unhealthy))
            current += timedelta(days=1)
        conn.executemany(
            """
            INSERT OR REPLACE INTO daily_alarm_summary (date, total_alarm, moderate_count, unhealthy_count)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )


def seed_sensors(start_date, end_date, devices, overwrite, simulate_ingest, topic):
    rng = random.Random(42)
    if simulate_ingest:
        with connect(SENSOR_DB) as conn:
            if overwrite:
                conn.execute("DELETE FROM sensor_readings")
                conn.execute("DELETE FROM alarm_events")
                conn.execute("DELETE FROM devices")
            for ts in iter_hourly_timestamps(start_date, end_date):
                readings = []
                for device_id, _, floor_id, zone, location_x, location_y, _, signal_quality in devices:
                    metrics = {}
                    for metric, config in METRICS.items():
                        value = rng.gauss(config["base"], config["variance"])
                        value = max(value, 0)
                        metrics[metric] = round(value, 2)
                    readings.append(
                        {
                            "device_id": device_id,
                            "model": "Milesight AM30x",
                            "floor_id": floor_id,
                            "zone": zone,
                            "location_x": location_x,
                            "location_y": location_y,
                            "signal_quality": signal_quality,
                            "ts": ts.isoformat(),
                            "topic": topic,
                            "metrics": metrics,
                        }
                    )
                ingest_milesight_payload({"readings": readings}, conn=conn)
    else:
        with connect(SENSOR_DB) as conn:
            if overwrite:
                conn.execute("DELETE FROM sensor_readings")
                conn.execute("DELETE FROM alarm_events")
                conn.execute("DELETE FROM devices")
            conn.executemany(
                """
                INSERT OR REPLACE INTO devices (
                    device_id, model, floor_id, zone, location_x, location_y, last_seen, signal_quality
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                devices,
            )

            insert_rows = []
            chunk_size = 5000
            for ts in iter_hourly_timestamps(start_date, end_date):
                for device_id, _, floor_id, _, _, _, _, _ in devices:
                    for metric, config in METRICS.items():
                        value = rng.gauss(config["base"], config["variance"])
                        value = max(value, 0)
                        insert_rows.append(
                            (
                                ts.isoformat(),
                                device_id,
                                floor_id,
                                metric,
                                round(value, 2),
                                config["unit"],
                                topic,
                            )
                        )
                        if len(insert_rows) >= chunk_size:
                            conn.executemany(
                                """
                                INSERT INTO sensor_readings (ts, device_id, floor_id, metric, value, unit, topic)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                insert_rows,
                            )
                            insert_rows.clear()
            if insert_rows:
                conn.executemany(
                    """
                    INSERT INTO sensor_readings (ts, device_id, floor_id, metric, value, unit, topic)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    insert_rows,
                )

    seed_calendar_summary(start_date, end_date, rng, overwrite)


def resolve_devices(args, rng):
    if args.all_devices:
        with connect(SENSOR_DB) as conn:
            devices, _ = load_devices_from_db(conn, rng=rng)
        if not devices:
            return generate_devices(args.sensors, rng)
        return devices
    if args.device:
        with connect(SENSOR_DB) as conn:
            devices, existing_ids = load_devices_from_db(conn, rng=rng, device_ids=args.device)
        missing_ids = [device_id for device_id in args.device if device_id not in existing_ids]
        for device_id in missing_ids:
            devices.append(build_device_record(device_id=device_id, rng=rng))
        return devices
    return generate_devices(args.sensors, rng)


def main():
    parser = argparse.ArgumentParser(
        description="Seed sensor data for a specific date range with optional overwrite."
    )
    parser.add_argument("--start", required=True, type=parse_date, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, type=parse_date, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--sensors",
        type=int,
        default=60,
        help="Number of sensors to create (default: 60)",
    )
    scope_group = parser.add_mutually_exclusive_group()
    scope_group.add_argument(
        "--device",
        action="append",
        help="Seed test data for a specific device (can be passed multiple times)",
    )
    scope_group.add_argument(
        "--all-devices",
        action="store_true",
        help="Seed test data for all existing devices",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Clear existing data before seeding",
    )
    parser.add_argument(
        "--simulate-ingest",
        action="store_true",
        help="Seed using the Milesight ingest path for simulated input",
    )
    parser.add_argument(
        "--topic",
        default="Live",
        help="Topic label to tag seeded data (default: Live)",
    )
    args = parser.parse_args()

    if args.end < args.start:
        parser.error("--end must be on or after --start")

    init_all()
    rng = random.Random(42)
    devices = resolve_devices(args, rng)
    seed_sensors(args.start, args.end, devices, args.overwrite, args.simulate_ingest, args.topic)


if __name__ == "__main__":
    main()
