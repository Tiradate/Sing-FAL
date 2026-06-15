import os
import unittest

os.environ.setdefault("ICON_SKIP_RUNTIME_BOOTSTRAP", "1")

import app


class SerialSourceAppStateTests(unittest.TestCase):
    def setUp(self):
        with app._SERIAL_SOURCE_EXECUTION_STATE_LOCK:
            app._SERIAL_SOURCE_EXECUTION_STATE.clear()

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


if __name__ == "__main__":
    unittest.main()
