CREATE TABLE IF NOT EXISTS daily_alarm_summary (
  date DATE PRIMARY KEY,
  total_alarm INTEGER,
  moderate_count INTEGER,
  unhealthy_count INTEGER
);
