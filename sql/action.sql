CREATE TABLE IF NOT EXISTS action_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alarm_event_id INTEGER,
    action_ts DATETIME,
    alarm_ts DATETIME,
    device_id TEXT,
    floor_id TEXT,
    metric TEXT,
    value REAL,
    severity TEXT,
    message TEXT,
    action_owner TEXT,
    action_note TEXT
);
