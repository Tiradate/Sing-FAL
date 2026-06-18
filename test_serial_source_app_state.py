import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("ICON_SKIP_RUNTIME_BOOTSTRAP", "1")

import app
from services import api_history as api_history_service
from services import db as db_service


class SerialSourceAppStateTests(unittest.TestCase):
    def setUp(self):
        with app._SERIAL_SOURCE_EXECUTION_STATE_LOCK:
            app._SERIAL_SOURCE_EXECUTION_STATE.clear()
        self._tmp_dir = TemporaryDirectory()
        self._api_db_path = os.path.join(self._tmp_dir.name, "api.db")
        self._api_db_patchers = [
            patch.object(app, "API_DB", self._api_db_path),
            patch.object(db_service, "API_DB", self._api_db_path),
            patch.object(api_history_service, "API_DB", self._api_db_path),
        ]
        for patcher in self._api_db_patchers:
            patcher.start()
        app.init_all()
        app.app.testing = True
        self.client = app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["is_admin"] = True

    def tearDown(self):
        with app._SERIAL_SOURCE_EXECUTION_STATE_LOCK:
            app._SERIAL_SOURCE_EXECUTION_STATE.clear()
        for patcher in reversed(getattr(self, "_api_db_patchers", [])):
            patcher.stop()
        if getattr(self, "_tmp_dir", None):
            self._tmp_dir.cleanup()

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

    def test_source_preview_export_csv_supports_serial_sources(self):
        with TemporaryDirectory() as tmp_dir:
            replay_path = Path(tmp_dir) / "serial.log"
            replay_path.write_text(
                "-OPERATOR COMMAND-  21:53:36  08/06/2026 P:07 C:00 D:02 AUX PORT 2\n"
                "DISABLE DEVICE\n"
                "P:05 C:03 D:0195\n\n"
                "COMMON TRBL ACT  ::  22:08:28 08/06/2026  P:05  C:03  D:0135\n"
                "BREW HOUSE #AZ-10    FL.1st STR LIGHT&HORN\n\n"
                "GND FAULT ACTIVE  ::  22:08:29 09/06/2026  P:05  C:03  D:0677\n"
                "05030677Ground Fault DataCard1\n\n",
                encoding="utf-8",
            )
            source = {
                "name": "Serial A",
                "format": "serial",
                "serial": {
                    "port": "COM3",
                    "baudrate": 9600,
                    "replay_file_path": str(replay_path),
                },
            }

            response = self.client.post(
                "/api/settings/source-preview/export.csv",
                json={
                    "source_name": source["name"],
                    "source": source,
                    "start_date": "2026-06-08",
                    "end_date": "2026-06-08",
                    "read_from_source": False,
                },
            )

            self.assertEqual(200, response.status_code)
            self.assertEqual("text/csv", response.mimetype)
            self.assertIn("source_data_Serial_A_2026-06-08_2026-06-08.csv", response.headers.get("Content-Disposition", ""))

            csv_text = response.get_data().decode("utf-8-sig")
            self.assertIn("id,created_at,effective_timestamp,source_name,parsed_ok", csv_text)
            self.assertIn("Serial A", csv_text)
            self.assertIn("COMMON TRBL ACT", csv_text)
            self.assertIn("BREW HOUSE #AZ-10    FL.1st STR LIGHT&HORN", csv_text)
            self.assertNotIn("GND FAULT ACTIVE", csv_text)

    def test_source_preview_export_csv_rejects_empty_serial_preview(self):
        source = {
            "name": "Serial A",
            "format": "serial",
            "serial": {
                "port": "COM3",
                "baudrate": 9600,
            },
        }

        response = self.client.post(
            "/api/settings/source-preview/export.csv",
            json={
                "source_name": source["name"],
                "source": source,
                "read_from_source": False,
            },
        )

        self.assertEqual(400, response.status_code)
        payload = response.get_json()
        self.assertIn("No serial records are available to export yet", payload.get("error", ""))

    def test_source_preview_export_csv_rejects_date_range_without_matches(self):
        with TemporaryDirectory() as tmp_dir:
            replay_path = Path(tmp_dir) / "serial.log"
            replay_path.write_text(
                "COMMON TRBL ACT  ::  22:08:28 09/06/2026  P:05  C:03  D:0135\n"
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
                },
            }

            response = self.client.post(
                "/api/settings/source-preview/export.csv",
                json={
                    "source_name": source["name"],
                    "source": source,
                    "start_date": "2026-06-08",
                    "end_date": "2026-06-08",
                    "read_from_source": False,
                },
            )

        self.assertEqual(400, response.status_code)
        payload = response.get_json()
        self.assertEqual("No serial records matched the selected date range.", payload.get("error"))

    def test_source_preview_logs_unparsed_serial_messages_for_export(self):
        with TemporaryDirectory() as tmp_dir:
            api_db_path = Path(tmp_dir) / "api.db"
            source = {
                "name": "Serial A",
                "format": "serial",
                "serial": {
                    "port": "COM3",
                    "baudrate": 9600,
                },
            }

            with patch.object(app, "API_DB", str(api_db_path)), patch("services.db.API_DB", str(api_db_path)):
                app.init_all()
                with patch(
                    "services.serial_source.read_serial_lines",
                    return_value=[
                        "UNPARSED HEADER",
                        "UNPARSED DETAIL",
                        "",
                    ],
                ):
                    preview_response = self.client.post(
                        "/api/settings/source-preview",
                        json={
                            "source_name": source["name"],
                            "source": source,
                        },
                    )

                self.assertEqual(200, preview_response.status_code)
                preview_payload = preview_response.get_json()
                self.assertEqual([], preview_payload.get("parsed_records", []))
                self.assertEqual(["UNPARSED HEADER", "UNPARSED DETAIL", ""], preview_payload.get("raw_lines"))

                export_response = self.client.post(
                    "/api/settings/source-preview/export.csv",
                    json={
                        "source_name": source["name"],
                        "source": source,
                        "read_from_source": False,
                    },
                )

            self.assertEqual(200, export_response.status_code)
            csv_text = export_response.get_data().decode("utf-8-sig")
            self.assertIn("UNPARSED HEADER\nUNPARSED DETAIL", csv_text)
            self.assertIn(",raw_message,", csv_text)
            self.assertIn(",0,,raw_message", csv_text)


if __name__ == "__main__":
    unittest.main()
