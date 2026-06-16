from contextlib import closing
import os
import sqlite3
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("ICON_SKIP_RUNTIME_BOOTSTRAP", "1")

import app


class SettingsLabelValidationTests(unittest.TestCase):
    def setUp(self):
        app.app.testing = True
        self.client = app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True

    def test_default_settings_enforce_sensor_label_type_position(self):
        self.assertTrue(app.settings_service.DEFAULT_SETTINGS["enforce_sensor_label_type_position"])

    def test_default_fire_tag_visibility_includes_beam(self):
        self.assertTrue(app.settings_service.DEFAULT_TAG_VISIBILITY["fire"]["beam"])

    def test_design_settings_can_disable_sensor_label_type_position_validation(self):
        with TemporaryDirectory() as tmp_dir:
            settings_path = os.path.join(tmp_dir, "settings.json")
            with patch.object(app.settings_service, "SETTINGS_PATH", settings_path), patch(
                "app.data_service.get_devices", return_value=[]
            ):
                initial_settings = app.settings_service.load_settings()
                self.assertTrue(initial_settings["enforce_sensor_label_type_position"])

                disable_response = self.client.post(
                    "/settings?tab=design",
                    data={"settings_section": "design"},
                )
                self.assertEqual(302, disable_response.status_code)

                disabled_settings = app.settings_service.load_settings()
                self.assertFalse(disabled_settings["enforce_sensor_label_type_position"])

                enable_response = self.client.post(
                    "/settings?tab=design",
                    data={
                        "settings_section": "design",
                        "enforce_sensor_label_type_position": "on",
                    },
                )
                self.assertEqual(302, enable_response.status_code)

                enabled_settings = app.settings_service.load_settings()
                self.assertTrue(enabled_settings["enforce_sensor_label_type_position"])

    def test_design_settings_can_save_beam_fire_mapping(self):
        with TemporaryDirectory() as tmp_dir:
            settings_path = os.path.join(tmp_dir, "settings.json")
            with patch.object(app.settings_service, "SETTINGS_PATH", settings_path), patch(
                "app.data_service.get_devices", return_value=[]
            ):
                response = self.client.post(
                    "/settings?tab=design",
                    data={
                        "settings_section": "design",
                        "fire_tag_beam": "on",
                        "fire_severity_label": ["Critical"],
                        "fire_severity_color": ["#dc3545"],
                        "fire_severity_text_color": ["#ffffff"],
                        "fire_severity_icon": [""],
                        "fire_smoke": [""],
                        "fire_heat": [""],
                        "fire_beam": ["BEAM"],
                        "fire_flow_switch": [""],
                        "fire_supervisory_valve": [""],
                        "fire_manual": [""],
                        "fire_gas": [""],
                        "critical_levels": ["Critical"],
                    },
                )
                self.assertEqual(302, response.status_code)

                saved_settings = app.settings_service.load_settings()
                self.assertTrue(saved_settings["tag_visibility"]["fire"]["beam"])
                self.assertEqual("BEAM", saved_settings["fire_severity_mapping"][0]["beam"])

    def test_source_settings_do_not_change_sensor_label_type_position_validation(self):
        with TemporaryDirectory() as tmp_dir:
            settings_path = os.path.join(tmp_dir, "settings.json")
            with patch.object(app.settings_service, "SETTINGS_PATH", settings_path), patch(
                "app.data_service.get_devices", return_value=[]
            ):
                initial_settings = app.settings_service.load_settings()
                self.assertTrue(initial_settings["enforce_sensor_label_type_position"])

                source_response = self.client.post(
                    "/settings?tab=source",
                    data={"settings_section": "source"},
                )
                self.assertEqual(302, source_response.status_code)

                preserved_settings = app.settings_service.load_settings()
                self.assertTrue(preserved_settings["enforce_sensor_label_type_position"])

    def test_design_tab_renders_sensor_label_validation_toggle_near_selected_item(self):
        with patch("app.data_service.get_devices", return_value=[]):
            response = self.client.get("/settings?tab=design")

        self.assertEqual(200, response.status_code)
        text = response.get_data(as_text=True)
        self.assertEqual(1, text.count('id="enforceSensorLabelTypePosition"'))
        self.assertLess(text.index('id="floorPlanEditor"'), text.index('id="enforceSensorLabelTypePosition"'))
        self.assertLess(text.index('id="enforceSensorLabelTypePosition"'), text.index('id="sensorZoneEditor"'))

    def test_design_tab_renders_bulk_sensor_label_controls(self):
        with patch("app.data_service.get_devices", return_value=[]):
            response = self.client.get("/settings?tab=design")

        self.assertEqual(200, response.status_code)
        text = response.get_data(as_text=True)
        self.assertIn('id="bulkSensorLabel"', text)
        self.assertIn('id="bulkSensorLabelError"', text)
        self.assertIn('{device_id}, {index}, {current_label}, {zone}, {sensor_type}', text)

    def test_settings_page_does_not_render_accounting_tab(self):
        with patch("app.data_service.get_devices", return_value=[]):
            response = self.client.get("/settings?tab=project")

        self.assertEqual(200, response.status_code)
        text = response.get_data(as_text=True)
        self.assertNotIn('data-settings-tab="account"', text)
        self.assertNotIn('data-settings-tab-panel="account"', text)
        self.assertNotIn("Save Accounting", text)

    def test_accounting_route_is_removed(self):
        response = self.client.get("/accounting")

        self.assertEqual(404, response.status_code)

    def _write_sensor_db(self, sensor_db_path, devices):
        with closing(sqlite3.connect(sensor_db_path)) as conn:
            conn.executescript(
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
                );
                """
            )
            for device in devices:
                conn.execute(
                    """
                    INSERT INTO devices (
                        device_id,
                        model,
                        floor_id,
                        zone,
                        label,
                        sensor_types,
                        location_x,
                        location_y,
                        sensor_icon,
                        last_seen,
                        signal_quality,
                        source_name,
                        source_device_name,
                        source_device_uuid
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device["device_id"],
                        device.get("model", "Milesight AM30x"),
                        device.get("floor_id", "F1"),
                        device.get("zone", "Z1"),
                        device.get("label"),
                        device.get("sensor_types", '["DZ"]'),
                        device.get("location_x", 50),
                        device.get("location_y", 50),
                        device.get("sensor_icon"),
                        device.get("last_seen", "2026-06-15T00:00:00+00:00"),
                        device.get("signal_quality", 100),
                        device.get("source_name"),
                        device.get("source_device_name"),
                        device.get("source_device_uuid"),
                    ),
                )
            conn.commit()

    def _patched_data_connect(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    def test_update_device_label_rejects_duplicate_label(self):
        with TemporaryDirectory() as tmp_dir:
            sensor_db_path = os.path.join(tmp_dir, "sensordata.db")
            self._write_sensor_db(
                sensor_db_path,
                [
                    {"device_id": "DEV-001", "label": "A-1F-Z1-DZ-1"},
                    {"device_id": "DEV-002", "label": "A-1F-Z2-DZ-2"},
                ],
            )
            with patch.object(app.data_service, "SENSOR_DB", sensor_db_path), patch.object(
                app.data_service, "connect", side_effect=self._patched_data_connect
            ):
                response = self.client.post(
                    "/api/devices/DEV-002/label",
                    json={"label": "A-1F-Z1-DZ-1"},
                )

            self.assertEqual(409, response.status_code)
            payload = response.get_json()
            self.assertEqual("Duplicate label", payload["error"])
            self.assertEqual("A-1F-Z1-DZ-1", payload["label"])
            self.assertEqual("DEV-001", payload["duplicate_device_id"])

            with closing(sqlite3.connect(sensor_db_path)) as conn:
                stored_label = conn.execute(
                    "SELECT label FROM devices WHERE device_id = ?",
                    ("DEV-002",),
                ).fetchone()[0]
            self.assertEqual("A-1F-Z2-DZ-2", stored_label)

    def test_create_device_rejects_duplicate_label(self):
        with TemporaryDirectory() as tmp_dir:
            sensor_db_path = os.path.join(tmp_dir, "sensordata.db")
            self._write_sensor_db(
                sensor_db_path,
                [
                    {"device_id": "DEV-001", "label": "A-1F-Z1-DZ-1"},
                ],
            )
            with patch.object(app.data_service, "SENSOR_DB", sensor_db_path), patch.object(
                app.data_service, "connect", side_effect=self._patched_data_connect
            ):
                response = self.client.post(
                    "/api/devices",
                    json={
                        "floor_id": "F1",
                        "zone": "Z1",
                        "sensor_type": "DZ",
                        "sensor_name": "A-1F-Z1-DZ-1",
                    },
                )

            self.assertEqual(409, response.status_code)
            payload = response.get_json()
            self.assertEqual("Duplicate label", payload["error"])
            self.assertEqual("DEV-001", payload["duplicate_device_id"])

            with closing(sqlite3.connect(sensor_db_path)) as conn:
                device_count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
            self.assertEqual(1, device_count)


if __name__ == "__main__":
    unittest.main()
