import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services import data as data_service
from services import serial_source


SERIAL_SAMPLE = """
-OPERATOR COMMAND-  21:53:36  08/06/2026 P:07 C:00 D:02 AUX PORT 2
DISABLE DEVICE
P:05 C:03 D:0195

DISABLED ACTIVE  ::  21:53:37 08/06/2026  P:05  C:03  D:0195
BH/Brew House beam_FL3 West Corridor_Zone1

COMMON TRBL ACT  ::  22:08:28 08/06/2026  P:05  C:03  D:0135
BREW HOUSE #AZ-10    FL.1st STR LIGHT&HORN

GND FAULT ACTIVE  ::  22:08:29 08/06/2026  P:05  C:03  D:0677
05030677Ground Fault DataCard1

"""


class SerialSourceParserTests(unittest.TestCase):
    def test_blank_line_records_are_split_individually(self):
        state = serial_source.parse_serial_text(SERIAL_SAMPLE, source_name="Serial A")
        parsed_records = state["parsed_records"]
        self.assertEqual(4, len(parsed_records))
        self.assertEqual("operator_command", parsed_records[0]["record_type"])
        self.assertEqual("event_status", parsed_records[1]["record_type"])
        self.assertEqual("event_status", parsed_records[2]["record_type"])
        self.assertEqual("event_status", parsed_records[3]["record_type"])

    def test_operator_record_uses_target_pcd_for_device_key(self):
        state = serial_source.parse_serial_text(SERIAL_SAMPLE, source_name="Serial A")
        operator_record = state["parsed_records"][0]
        self.assertEqual("p05-c03-d0195", operator_record["device_key"])
        self.assertEqual("05", operator_record["fields"]["target_p"])
        self.assertEqual("03", operator_record["fields"]["target_c"])
        self.assertEqual("0195", operator_record["fields"]["target_d"])
        self.assertEqual("07", operator_record["fields"]["command_source_p"])

    def test_event_status_record_keeps_event_fields(self):
        state = serial_source.parse_serial_text(SERIAL_SAMPLE, source_name="Serial A")
        event_record = state["parsed_records"][2]
        self.assertEqual("COMMON TRBL ACT", event_record["fields"]["event_text"])
        self.assertEqual("BREW HOUSE #AZ-10    FL.1st STR LIGHT&HORN", event_record["fields"]["event_description"])
        self.assertEqual("p05-c03-d0135", event_record["device_key"])

    def test_partial_record_waits_for_blank_line(self):
        first_chunk = """
-OPERATOR COMMAND-  21:53:36  08/06/2026 P:07 C:00 D:02 AUX PORT 2
DISABLE DEVICE
P:05 C:03 D:0195
""".strip().splitlines()
        state = serial_source.apply_stream_lines({}, first_chunk, source_name="Serial A")
        self.assertEqual([], state["parsed_records"])
        self.assertEqual(3, len(state["partial_record"]))

        state = serial_source.apply_stream_lines(state, [""], source_name="Serial A")
        self.assertEqual(1, len(state["parsed_records"]))
        self.assertEqual([], state["partial_record"])

    def test_latest_values_and_devices_are_built_from_records(self):
        state = serial_source.parse_serial_text(SERIAL_SAMPLE, source_name="Serial A")
        latest_values = state["latest_values"]["items"]
        device_items = state["device_items"]
        ready_device_items = serial_source.build_ready_device_items(device_items, state["latest_values"])
        device_keys = sorted(item["device_uuid"] for item in latest_values)
        self.assertEqual(
            ["p05-c03-d0135", "p05-c03-d0195", "p05-c03-d0677"],
            device_keys,
        )
        self.assertEqual(3, len(device_items))
        self.assertEqual(3, len(ready_device_items))

    def test_replay_start_stop_resume_controls_live_source_pause(self):
        with TemporaryDirectory() as tmp_dir:
            replay_path = Path(tmp_dir) / "serial.log"
            replay_path.write_text(
                "-OPERATOR COMMAND-  21:53:36  08/06/2026 P:07 C:00 D:02 AUX PORT 2\n"
                "DISABLE DEVICE\n"
                "P:05 C:03 D:0195\n\n",
                encoding="utf-8",
            )

            state = serial_source.apply_replay_action(
                {},
                {
                    "replay_file_path": str(replay_path),
                    "replay_interval_seconds": 60,
                },
                "start",
            )
            self.assertTrue(state["live_source_paused"])
            self.assertTrue(state["replay"]["active"])

            state = serial_source.apply_replay_action(state, {}, "stop")
            self.assertTrue(state["live_source_paused"])
            self.assertFalse(state["replay"]["active"])

            state = serial_source.apply_replay_action(state, {}, "resume_source")
            self.assertFalse(state["live_source_paused"])
            self.assertFalse(state["replay"]["active"])

    def test_paused_live_source_skips_real_serial_reads(self):
        with patch.object(serial_source, "read_serial_lines", return_value=["SHOULD NOT READ"]) as mocked_read:
            state, raw_lines = serial_source._read_source_lines(
                {"live_source_paused": True},
                {"port": "COM3"},
                read_from_source=True,
            )

        mocked_read.assert_not_called()
        self.assertTrue(state["live_source_paused"])
        self.assertEqual([], raw_lines)

    def test_latest_values_include_serial_sensor_field_entries(self):
        state = serial_source.parse_serial_text(SERIAL_SAMPLE, source_name="Serial A")
        event_item = next(
            item for item in state["latest_values"]["items"] if item["device_uuid"] == "p05-c03-d0135"
        )
        event_fields = {entry["field"]: entry for entry in event_item["values"]}
        discovery_payload = serial_source.build_field_discovery_payload_from_text(
            SERIAL_SAMPLE,
            source_name="Serial A",
        )
        discovery_fields = {
            entry["field"]
            for item in discovery_payload["items"]
            for entry in item.get("values", [])
            if entry.get("field_role") == serial_source.SERIAL_SENSOR_FIELD_ROLE
        }

        self.assertIn("-OPERATOR COMMAND-", discovery_fields)
        self.assertIn("COMMON TRBL ACT", event_fields)
        self.assertEqual(
            "BREW HOUSE #AZ-10    FL.1st STR LIGHT&HORN",
            event_fields["COMMON TRBL ACT"]["value"],
        )
        self.assertEqual(
            serial_source.SERIAL_SENSOR_FIELD_ROLE,
            event_fields["COMMON TRBL ACT"]["field_role"],
        )

    def test_field_discovery_payload_from_text_collects_serial_event_categories(self):
        payload = serial_source.build_field_discovery_payload_from_text(SERIAL_SAMPLE, source_name="Serial A")
        discovered_fields = {
            entry["field"]
            for item in payload["items"]
            for entry in item.get("values", [])
            if entry.get("field_role") == serial_source.SERIAL_SENSOR_FIELD_ROLE
        }

        self.assertIn("-OPERATOR COMMAND-", discovered_fields)
        self.assertIn("DISABLED ACTIVE", discovered_fields)
        self.assertIn("COMMON TRBL ACT", discovered_fields)
        self.assertIn("GND FAULT ACTIVE", discovered_fields)


class SerialSourceIngestTests(unittest.TestCase):
    def test_sync_source_metric_fields_uses_serial_field_roles(self):
        settings = {"source_metric_fields": []}
        payload = serial_source.build_field_discovery_payload_from_text(
            SERIAL_SAMPLE,
            source_name="Serial A",
        )

        updated = data_service.sync_source_metric_fields(settings, "Serial A", payload)

        self.assertTrue(updated)
        field_map = {
            field["source_field"]: field
            for field in data_service.get_source_metric_fields(settings)
        }
        self.assertTrue(field_map["COMMON TRBL ACT"]["show_in_bulk_type"])
        self.assertTrue(field_map["COMMON TRBL ACT"]["save_to_db"])
        self.assertFalse(field_map["COMMON TRBL ACT"]["enable_severity"])
        self.assertFalse(field_map["event_text"]["show_in_bulk_type"])
        self.assertFalse(field_map["event_text"]["save_to_db"])

    def test_resolve_device_display_zone_uses_serial_detail_for_all_zone(self):
        zone = data_service.resolve_device_display_zone(
            {
                "device_id": "FIRE-ALARM-7",
                "zone": "ALL",
                "label": "BREW HOUSE",
                "source_name": "SING FCP",
            },
            {
                "alarm active": {
                    "ts": "2026-06-11T07:56:28+07:00",
                    "raw_value": "BH/Brew House beam_FL3 West Corridor_Zone1",
                    "value": None,
                    "unit": "",
                }
            },
        )

        self.assertEqual("beam_FL3 West Corridor_Zone1", zone)

    def test_find_fire_matches_supports_beam_detector(self):
        matches = data_service._find_fire_matches(
            [{"label": "Critical", "beam": "BEAM"}],
            "BH/Brew House beam_FL3 West Corridor_Zone1",
        )

        self.assertEqual(
            [
                {
                    "severity": "Critical",
                    "metric": "beam",
                    "message": "Beam: BEAM",
                }
            ],
            matches,
        )

    def test_ingest_source_latest_values_payload_matches_label_and_clears_restored_alarm(self):
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "sensordata.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
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
                );
                CREATE TABLE alarm_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts DATETIME,
                    device_id TEXT,
                    floor_id TEXT,
                    metric TEXT,
                    value REAL,
                    severity TEXT,
                    message TEXT,
                    active INTEGER DEFAULT 1
                );
                """
            )
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
                    "DEV-001",
                    "Fire Panel",
                    "F1",
                    "Z1",
                    "BREW HOUSE",
                    data_service.serialize_device_sensor_types(["ALARM ACTIVE", "ALARM RESTORED"]),
                    50,
                    50,
                    None,
                    "2026-06-10T00:00:00+07:00",
                    100,
                    None,
                    None,
                    None,
                ),
            )
            settings = {
                "source_metric_fields": [
                    {
                        "key": "alarm active",
                        "source_field": "ALARM ACTIVE",
                        "field_role": data_service.SERIAL_SENSOR_FIELD_ROLE,
                        "save_to_db": True,
                        "show_in_bulk_type": True,
                    },
                    {
                        "key": "alarm restored",
                        "source_field": "ALARM RESTORED",
                        "field_role": data_service.SERIAL_SENSOR_FIELD_ROLE,
                        "save_to_db": True,
                        "show_in_bulk_type": True,
                    },
                ],
                "fire_severity_mapping": [
                    {
                        "label": "Critical",
                        "manual": "AZ",
                    }
                ],
                "critical_levels": [],
            }
            active_payload = {
                "items": [
                    {
                        "device_uuid": "p05-c03-d0195",
                        "display_name": "P:05 C:03 D:0195",
                        "values": [
                            {
                                "field": "ALARM ACTIVE",
                                "value": "BH/Brew House beam_FL3 West Corridor_Zone1 #AZ",
                                "field_role": data_service.SERIAL_SENSOR_FIELD_ROLE,
                                "ts": "2026-06-10T06:50:47+07:00",
                            }
                        ],
                    }
                ]
            }

            active_result = data_service.ingest_source_latest_values_payload(
                active_payload,
                source_name="Serial A",
                settings=settings,
                conn=conn,
            )
            conn.commit()

            self.assertEqual(1, active_result["matched_devices"])
            self.assertEqual(1, active_result["inserted"])
            active_alarm = conn.execute(
                "SELECT metric, severity, message, active FROM alarm_events WHERE device_id = ?",
                ("DEV-001",),
            ).fetchone()
            self.assertIsNotNone(active_alarm)
            self.assertEqual("manual", active_alarm["metric"])
            self.assertEqual("Critical", active_alarm["severity"])
            self.assertEqual(1, active_alarm["active"])

            restore_payload = {
                "items": [
                    {
                        "device_uuid": "p05-c03-d0195",
                        "display_name": "P:05 C:03 D:0195",
                        "values": [
                            {
                                "field": "ALARM RESTORED",
                                "value": "BH/Brew House beam_FL3 West Corridor_Zone1 #AZ",
                                "field_role": data_service.SERIAL_SENSOR_FIELD_ROLE,
                                "ts": "2026-06-10T06:51:08+07:00",
                            }
                        ],
                    }
                ]
            }

            restore_result = data_service.ingest_source_latest_values_payload(
                restore_payload,
                source_name="Serial A",
                settings=settings,
                conn=conn,
            )
            conn.commit()

            self.assertEqual(1, restore_result["matched_devices"])
            self.assertEqual(
                0,
                conn.execute(
                    "SELECT COUNT(*) FROM alarm_events WHERE device_id = ? AND active = 1",
                    ("DEV-001",),
                ).fetchone()[0],
            )
            conn.close()


if __name__ == "__main__":
    unittest.main()
