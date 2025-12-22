CREATE TABLE IF NOT EXISTS alarm_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts DATETIME,
  device_id TEXT,
  floor_id TEXT,
  metric TEXT,
  value REAL,
  severity TEXT,
  message TEXT
);
