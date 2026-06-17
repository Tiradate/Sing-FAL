import copy
import gc
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("ICON_SKIP_RUNTIME_BOOTSTRAP", "1")

import app


def seed_sensor_db(db_path, *, devices, readings):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE devices (
            device_id TEXT PRIMARY KEY,
            model TEXT,
            floor_id TEXT,
            zone TEXT,
            label TEXT,
            sensor_types TEXT,
            location_x REAL,
            location_y REAL,
            sensor_icon TEXT,
            last_seen DATETIME,
            signal_quality INTEGER,
            source_name TEXT,
            source_device_name TEXT,
            source_device_uuid TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME,
            ingested_at DATETIME,
            device_id TEXT,
            floor_id TEXT,
            metric TEXT,
            value REAL,
            raw_value TEXT,
            unit TEXT,
            topic TEXT DEFAULT 'Live'
        )
        """
    )
    for device in devices:
        conn.execute(
            """
            INSERT INTO devices (
                device_id, model, floor_id, zone, label, sensor_types, location_x, location_y,
                sensor_icon, last_seen, signal_quality, source_name, source_device_name, source_device_uuid
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device.get("device_id"),
                device.get("model"),
                device.get("floor_id"),
                device.get("zone"),
                device.get("label"),
                device.get("sensor_types"),
                device.get("location_x"),
                device.get("location_y"),
                device.get("sensor_icon"),
                device.get("last_seen"),
                device.get("signal_quality"),
                device.get("source_name"),
                device.get("source_device_name"),
                device.get("source_device_uuid"),
            ),
        )
    for reading in readings:
        conn.execute(
            """
            INSERT INTO sensor_readings (
                ts, ingested_at, device_id, floor_id, metric, value, raw_value, unit, topic
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reading.get("ts"),
                reading.get("ingested_at"),
                reading.get("device_id"),
                reading.get("floor_id"),
                reading.get("metric"),
                reading.get("value"),
                reading.get("raw_value"),
                reading.get("unit"),
                reading.get("topic", "Live"),
            ),
        )
    conn.commit()
    conn.close()


class DownloadExportTests(unittest.TestCase):
    def setUp(self):
        with app._FIRE_REPORT_EXPORT_JOB_LOCK:
            app._FIRE_REPORT_EXPORT_JOBS.clear()

    def tearDown(self):
        with app._FIRE_REPORT_EXPORT_JOB_LOCK:
            app._FIRE_REPORT_EXPORT_JOBS.clear()

    def test_csv_export_filters_by_range_and_system_metrics(self):
        settings = copy.deepcopy(app.settings_service.DEFAULT_SETTINGS)
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "sensordata.db")
            seed_sensor_db(
                db_path,
                devices=[
                    {
                        "device_id": "FIRE-01",
                        "model": "Panel",
                        "floor_id": "F1",
                        "zone": "Zone A",
                        "label": "Fire Sensor 01",
                    }
                ],
                readings=[
                    {
                        "ts": "2026-06-01T10:00:00",
                        "ingested_at": "2026-06-01T10:00:00",
                        "device_id": "FIRE-01",
                        "floor_id": "F1",
                        "metric": "smoke",
                        "value": None,
                        "raw_value": "SMOKE ALARM",
                        "unit": "",
                        "topic": "Live",
                    },
                    {
                        "ts": "2026-06-01T11:00:00",
                        "ingested_at": "2026-06-01T11:00:00",
                        "device_id": "FIRE-01",
                        "floor_id": "F1",
                        "metric": "temperature",
                        "value": 25.0,
                        "raw_value": "25.0",
                        "unit": "C",
                        "topic": "Live",
                    },
                    {
                        "ts": "2026-05-25T09:00:00",
                        "ingested_at": "2026-05-25T09:00:00",
                        "device_id": "FIRE-01",
                        "floor_id": "F1",
                        "metric": "heat",
                        "value": None,
                        "raw_value": "OUTSIDE RANGE",
                        "unit": "",
                        "topic": "Live",
                    },
                ],
            )
            export_context = app._build_sensor_export_context(
                settings,
                {
                    "system": "fire",
                    "start": "2026-06-01T00:00",
                    "end": "2026-06-01T23:59",
                },
            )
            with patch.object(app.data_service, "SENSOR_DB", db_path):
                with app.app.test_request_context("/"):
                    csv_bytes, filename = app._build_sensor_export_csv_bytes(
                        settings,
                        export_context,
                    )
            gc.collect()

        csv_text = csv_bytes.getvalue().decode("utf-8-sig")
        self.assertTrue(filename.endswith(".csv"))
        self.assertIn("SMOKE ALARM", csv_text)
        self.assertIn("Fire Sensor 01", csv_text)
        self.assertIn(",smoke,", csv_text)
        self.assertNotIn(",temperature,", csv_text)
        self.assertNotIn("OUTSIDE RANGE", csv_text)

    def test_fire_pdf_context_rejects_ranges_longer_than_31_days(self):
        settings = copy.deepcopy(app.settings_service.DEFAULT_SETTINGS)

        with self.assertRaisesRegex(ValueError, "31 days"):
            app._build_sensor_export_context(
                settings,
                {
                    "system": "fire",
                    "start": "2026-01-01T00:00",
                    "end": "2026-02-02T00:01",
                },
                require_fire=True,
                max_range=app.FIRE_REPORT_EXPORT_MAX_RANGE,
            )

    def test_fire_pdf_job_creates_downloadable_pdf(self):
        settings = copy.deepcopy(app.settings_service.DEFAULT_SETTINGS)
        settings["project_name"] = "Test Fire Dashboard"
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "sensordata.db")
            export_dir = os.path.join(tmp_dir, "exports")
            os.makedirs(export_dir, exist_ok=True)
            seed_sensor_db(
                db_path,
                devices=[
                    {
                        "device_id": "FIRE-02",
                        "model": "Panel",
                        "floor_id": "F2",
                        "zone": "Zone B",
                        "label": "Fire Sensor 02",
                    }
                ],
                readings=[
                    {
                        "ts": "2026-06-01T08:30:00",
                        "ingested_at": "2026-06-01T08:30:00",
                        "device_id": "FIRE-02",
                        "floor_id": "F2",
                        "metric": "beam",
                        "value": None,
                        "raw_value": "BEAM TROUBLE",
                        "unit": "",
                        "topic": "Live",
                    }
                ],
            )
            export_context = app._build_sensor_export_context(
                settings,
                {
                    "system": "fire",
                    "start": "2026-06-01T00:00",
                    "end": "2026-06-01T23:59",
                },
                require_fire=True,
                max_range=app.FIRE_REPORT_EXPORT_MAX_RANGE,
            )
            with patch.object(app.data_service, "SENSOR_DB", db_path), patch.object(
                app,
                "_FIRE_REPORT_EXPORT_DIR",
                export_dir,
            ):
                with app.app.test_request_context("/"):
                    app.session["user_id"] = "1"
                    app.session["username"] = "tester"
                    job = app._start_fire_report_export_job(settings, export_context)
                    self.assertIsNotNone(job)

                    completed_job = None
                    for _ in range(80):
                        current_job = app._get_fire_report_export_job_for_current_user(
                            job["job_id"]
                        )
                        if current_job and current_job.get("status") in {"completed", "error"}:
                            completed_job = current_job
                            break
                        time.sleep(0.05)
                    self.assertIsNotNone(completed_job)
                    self.assertEqual(
                        "completed",
                        completed_job["status"],
                        msg=completed_job.get("error"),
                    )
                    self.assertTrue(os.path.isfile(completed_job["file_path"]))
                    with open(completed_job["file_path"], "rb") as handle:
                        self.assertEqual(b"%PDF", handle.read(4))
            gc.collect()


if __name__ == "__main__":
    unittest.main()
