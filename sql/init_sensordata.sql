CREATE TABLE IF NOT EXISTS devices (
  device_id TEXT PRIMARY KEY,
  model TEXT,
  floor_id TEXT,
  zone TEXT,
  location_x REAL,
  location_y REAL,
  last_seen DATETIME,
  signal_quality INTEGER
);

CREATE TABLE IF NOT EXISTS sensor_readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts DATETIME,
  device_id TEXT,
  floor_id TEXT,
  metric TEXT,
  value REAL,
  unit TEXT
);

CREATE TABLE IF NOT EXISTS alarm_events (
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
