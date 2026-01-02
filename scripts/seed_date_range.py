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


def generate_devices(count, rng):
    devices = []
    for index in range(1, count + 1):
        device_id = f"AM30X-{index:03d}"
        floor = FLOORS[(index - 1) % len(FLOORS)]
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


def seed_sensors(start_date, end_date, sensor_count, overwrite):
    rng = random.Random(42)
    devices = generate_devices(sensor_count, rng)
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
                        )
                    )
                    if len(insert_rows) >= chunk_size:
                        conn.executemany(
                            """
                            INSERT INTO sensor_readings (ts, device_id, floor_id, metric, value, unit)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            insert_rows,
                        )
                        insert_rows.clear()
        if insert_rows:
            conn.executemany(
                """
                INSERT INTO sensor_readings (ts, device_id, floor_id, metric, value, unit)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                insert_rows,
            )

    seed_calendar_summary(start_date, end_date, rng, overwrite)


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
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Clear existing data before seeding",
    )
    args = parser.parse_args()

    if args.end < args.start:
        parser.error("--end must be on or after --start")

    init_all()
    seed_sensors(args.start, args.end, args.sensors, args.overwrite)


if __name__ == "__main__":
    main()
