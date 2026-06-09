import unittest

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


if __name__ == "__main__":
    unittest.main()
