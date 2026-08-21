DROP TABLE IF EXISTS timeline_events;
CREATE TABLE timeline_events (
  id TEXT NOT NULL PRIMARY KEY,
  event_date DATE NOT NULL,               -- 活动日期（YYYY-MM-DD）
  event TEXT NOT NULL DEFAULT '',         -- 活动名（即照片 timeline 值）
  note TEXT NOT NULL DEFAULT '',          -- 备注
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
