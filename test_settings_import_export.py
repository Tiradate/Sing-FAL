import os
import unittest

os.environ.setdefault("ICON_SKIP_RUNTIME_BOOTSTRAP", "1")

import app as sing_app


LONG_LABEL = "OVER NIGHT TRUCK AND TRUCK PARK-1F-Z1-DZ-1"


class SettingsImportExportTests(unittest.TestCase):
    def test_build_settings_export_payload_uses_sensor_positions_only(self):
        payload = sing_app._build_settings_export_payload(
            {"project_name": "Sing", "floor_plan_sensors": {"legacy": []}},
            [
                {
                    "device_id": "FIRE-ALARM-24",
                    "floor_id": "Fire Alarm",
                    "label": LONG_LABEL,
                    "location_x": 8.80262,
                    "location_y": 97.6595,
                    "source_name": None,
                    "source_device_name": None,
                    "source_device_uuid": None,
                }
            ],
        )

        self.assertNotIn("floor_plan_sensors", payload)
        self.assertEqual(1, len(payload["sensor_positions"]))
        self.assertEqual(LONG_LABEL, payload["sensor_positions"][0]["label"])

    def test_parse_sensor_layouts_preserves_long_sensor_label(self):
        layouts = sing_app._parse_sensor_layouts(
            [
                {
                    "device_id": "FIRE-ALARM-24",
                    "label": LONG_LABEL,
                    "location_x": "8.80262",
                    "location_y": "97.6595",
                }
            ],
            floor_id_hint="Fire Alarm",
        )

        self.assertEqual(1, len(layouts))
        self.assertEqual(LONG_LABEL, layouts[0]["label"])
        self.assertEqual("Fire Alarm", layouts[0]["floor_id"])

    def test_resolve_imported_sensor_layouts_falls_back_to_legacy_rows(self):
        legacy_layouts = [
            {
                "device_id": "FIRE-ALARM-24",
                "floor_id": "Fire Alarm",
                "label": LONG_LABEL,
                "location_x": 8.80262,
                "location_y": 97.6595,
                "source_name": None,
                "source_device_name": None,
                "source_device_uuid": None,
            }
        ]

        resolved = sing_app._resolve_imported_sensor_layouts(
            {"floor_plan_sensors": legacy_layouts}
        )

        self.assertEqual(LONG_LABEL, resolved[0]["label"])

    def test_resolve_imported_sensor_layouts_prefers_sensor_positions(self):
        resolved = sing_app._resolve_imported_sensor_layouts(
            {
                "floor_plan_sensors": [
                    {
                        "device_id": "FIRE-ALARM-24",
                        "floor_id": "Fire Alarm",
                        "label": "OLD LABEL-1F-Z1-DZ-1",
                        "location_x": 8.80262,
                        "location_y": 97.6595,
                    }
                ],
                "sensor_positions": [
                    {
                        "device_id": "FIRE-ALARM-24",
                        "floor_id": "Fire Alarm",
                        "label": LONG_LABEL,
                        "location_x": 8.80262,
                        "location_y": 97.6595,
                    }
                ],
            }
        )

        self.assertEqual(LONG_LABEL, resolved[0]["label"])


if __name__ == "__main__":
    unittest.main()
