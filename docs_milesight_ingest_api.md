# Milesight Ingest API (Integrator Guide)

This guide documents the HTTP API used to send Milesight sensor data into this web application.

## Endpoint

`POST /api/ingest/milesight`

## Authentication

If an **ingest token** is configured, every request must include the header:

```
X-API-Key: <ingest_token>
```

The ingest token is stored in `settings.json` as `ingest_token`. When the token is **not** set, the endpoint accepts unauthenticated requests.

## Content Type

```
Content-Type: application/json
```

## Payload format

The endpoint expects a JSON object containing a list of readings. The list can be provided directly or under one of these keys:

- `readings`
- `records`
- `devices`

Example with `readings`:

```json
{
  "readings": [
    {
      "device_id": "lobby-1",
      "floor_id": "floor-1",
      "model": "Milesight AM319",
      "signal_quality": 98,
      "timestamp": "2024-08-22T04:05:06Z",
      "topic": "Live",
      "metrics": {
        "temperature": 25.6,
        "humidity": 49.1,
        "co2": 612
      }
    }
  ]
}
```

### Reading fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `device_id` | string | ✅ | Must match an existing device in the database. If missing, the API tries `device_eui` or `dev_eui`. |
| `floor_id` | string | ❌ | Optional. The system uses the floor assigned to the device record instead. |
| `model` | string | ❌ | Defaults to `Milesight AM30x`. |
| `signal_quality` | number | ❌ | Defaults to `100`. |
| `timestamp` or `ts` | string/number | ❌ | ISO-8601 string or epoch seconds/milliseconds. Defaults to current time. |
| `topic` | string | ❌ | Defaults to `Live`. |
| `metrics` (or `data`) | object | ✅ | Key/value map of sensor metrics. Unsupported metrics are ignored. |

### Supported metrics

The ingest pipeline only accepts the metrics below (aliases shown). All values must be numeric.

| Normalized key | Accepted aliases | Unit |
| --- | --- | --- |
| `temperature` | `temperature`, `temp` | °C |
| `humidity` | `humidity` | %RH |
| `co2` | `co2` | ppm |
| `pm25` | `pm25`, `pm2.5`, `pm2_5` | µg/m³ |
| `pm10` | `pm10` | µg/m³ |
| `tvoc` | `tvoc` | mg/m³ |

## Response

On success:

```json
{
  "inserted": 3,
  "created_devices": 0
}
```

On error (bad payload):

```json
{
  "error": "Payload must include a list of readings"
}
```

## Important behavior

- **Devices must exist first.** Readings for unknown devices are ignored. Add devices via the admin UI or the admin-only API endpoint `POST /api/devices`.
- **Floor validation.** If the application has `floor_plans` configured, only devices assigned to those floors are accepted.
- **Per-metric inserts.** Each metric becomes its own row in `sensor_readings` with normalized units.

## Python example (requests)

```python
import requests

base_url = "http://<host>:<port>"
api_key = "<ingest_token>"  # leave None if ingest_token is not configured

payload = {
    "readings": [
        {
            "device_id": "lobby-1",
            "timestamp": "2024-08-22T04:05:06Z",
            "metrics": {
                "temperature": 25.6,
                "humidity": 49.1,
                "co2": 612,
            },
        }
    ]
}

headers = {"Content-Type": "application/json"}
if api_key:
    headers["X-API-Key"] = api_key

response = requests.post(
    f"{base_url}/api/ingest/milesight",
    json=payload,
    headers=headers,
    timeout=10,
)

response.raise_for_status()
print(response.json())
```
