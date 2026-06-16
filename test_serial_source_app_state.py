import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("ICON_SKIP_RUNTIME_BOOTSTRAP", "1")

import app


class SerialSourceAppStateTests(unittest.TestCase):
    def setUp(self):
        with app._SERIAL_SOURCE_EXECUTION_STATE_LOCK:
            app._SERIAL_SOURCE_EXECUTION_STATE.clear()
        app.app.testing = True
        self.client = app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True

    def tearDown(self):
        with app._SERIAL_SOURCE_EXECUTION_STATE_LOCK:
            app._SERIAL_SOURCE_EXECUTION_STATE.clear()

    def test_get_serial_source_execution_state_preserves_test_mode_across_signature_changes(self):
        preview_source = {
            "name": "Serial A",
            "format": "serial",
            "serial": {
                "port": "COM3",
                "baudrate": 9600,
                "replay_file_path": "C:/temp/serial.log",
            },
        }
        saved_source = {
            "name": "Serial A",
            "format": "serial",
            "serial": {
                "port": "COM3",
                "baudrate": 9600,
                "replay_file_path": "",
            },
        }

        app._save_serial_source_execution_state(
            preview_source,
            {
                "live_source_paused": True,
                "replay": {
                    "active": True,
                    "file_path": "C:/temp/serial.log",
                    "interval_seconds": 60,
                },
            },
        )

        preserved_state = app._get_serial_source_execution_state(saved_source)

        self.assertTrue(preserved_state["live_source_paused"])
        self.assertTrue(preserved_state["replay"]["active"])
        self.assertEqual("C:/temp/serial.log", preserved_state["replay"]["file_path"])

    def test_latest_values_poll_interval_is_zero_when_live_source_is_paused(self):
        source = {
            "name": "Serial A",
            "format": "serial",
            "serial": {
                "port": "COM3",
                "baudrate": 9600,
            },
        }
        app._save_serial_source_execution_state(
            source,
            {
                "live_source_paused": True,
                "replay": {
                    "active": False,
                    "file_path": "C:/temp/serial.log",
                    "interval_seconds": 60,
                },
            },
        )

        interval_seconds = app._latest_values_poll_interval_seconds(source)

        self.assertEqual(0, interval_seconds)

    def test_source_preview_route_stops_live_source_until_use_source_resumes_it(self):
        with TemporaryDirectory() as tmp_dir:
            replay_path = Path(tmp_dir) / "serial.log"
            replay_path.write_text(
                "-OPERATOR COMMAND-  21:53:36  08/06/2026 P:07 C:00 D:02 AUX PORT 2\n"
                "DISABLE DEVICE\n"
                "P:05 C:03 D:0195\n\n"
                "COMMON TRBL ACT  ::  22:08:28 08/06/2026  P:05  C:03  D:0135\n"
                "BREW HOUSE #AZ-10    FL.1st STR LIGHT&HORN\n\n",
                encoding="utf-8",
            )
            source = {
                "name": "Serial A",
                "format": "serial",
                "serial": {
                    "port": "COM3",
                    "baudrate": 9600,
                    "replay_file_path": str(replay_path),
                    "replay_interval_seconds": 60,
                },
            }

            start_response = self.client.post(
                "/api/settings/source-preview",
                json={
                    "source_name": source["name"],
                    "source": source,
                    "serial_replay_action": "start",
                },
            )
            self.assertEqual(200, start_response.status_code)
            start_payload = start_response.get_json()
            self.assertTrue(start_payload["execution_state"]["live_source_paused"])
            self.assertTrue(start_payload["execution_state"]["replay"]["active"])

            stop_response = self.client.post(
                "/api/settings/source-preview",
                json={
                    "source_name": source["name"],
                    "source": source,
                    "serial_replay_action": "stop",
                    "read_from_source": False,
                },
            )
            self.assertEqual(200, stop_response.status_code)
            stop_payload = stop_response.get_json()
            self.assertTrue(stop_payload["execution_state"]["live_source_paused"])
            self.assertFalse(stop_payload["execution_state"]["replay"]["active"])

            with patch("services.serial_source.read_serial_lines", return_value=["TEST LIVE LINE"]):
                resume_response = self.client.post(
                    "/api/settings/source-preview",
                    json={
                        "source_name": source["name"],
                        "source": source,
                        "serial_replay_action": "resume_source",
                    },
                )
            self.assertEqual(200, resume_response.status_code)
            resume_payload = resume_response.get_json()
            self.assertFalse(resume_payload["execution_state"]["live_source_paused"])
            self.assertFalse(resume_payload["execution_state"]["replay"]["active"])
            self.assertIn("TEST LIVE LINE", resume_payload["raw_lines"])

    def test_source_preview_route_discovers_serial_sensor_fields_from_replay_file(self):
        with TemporaryDirectory() as tmp_dir:
            replay_path = Path(tmp_dir) / "serial.log"
            settings_path = Path(tmp_dir) / "settings.json"
            replay_path.write_text(
                "-OPERATOR COMMAND-  21:53:36  08/06/2026 P:07 C:00 D:02 AUX PORT 2\n"
                "DISABLE DEVICE\n"
                "P:05 C:03 D:0195\n\n"
                "COMMON TRBL ACT  ::  22:08:28 08/06/2026  P:05  C:03  D:0135\n"
                "BREW HOUSE #AZ-10    FL.1st STR LIGHT&HORN\n\n",
                encoding="utf-8",
            )
            source = {
                "name": "Serial A",
                "format": "serial",
                "serial": {
                    "port": "COM3",
                    "baudrate": 9600,
                    "replay_file_path": str(replay_path),
                    "replay_interval_seconds": 60,
                },
            }

            with patch.object(app.settings_service, "SETTINGS_PATH", str(settings_path)), patch(
                "app.data_service.ingest_source_latest_values_payload",
                return_value={"inserted": 0, "matched_devices": 0},
            ):
                response = self.client.post(
                    "/api/settings/source-preview",
                    json={
                        "source_name": source["name"],
                        "source": source,
                        "serial_replay_action": "start",
                    },
                )

            self.assertEqual(200, response.status_code)
            payload = response.get_json()
            source_fields = {
                field.get("source_field")
                for field in payload.get("source_metric_fields", [])
            }
            self.assertIn("-OPERATOR COMMAND-", source_fields)
            self.assertIn("COMMON TRBL ACT", source_fields)


if __name__ == "__main__":
    unittest.main()
