DROP TABLE IF EXISTS photo_groups;
CREATE TABLE photo_groups (
  id TEXT NOT NULL PRIMARY KEY,            -- burst_<profile>_<首照片id前8位>
  cover_photo_id TEXT NOT NULL DEFAULT '', -- 逻辑指向 photos.id，无外键约束
  profile TEXT NOT NULL DEFAULT 'fine',    -- 参数档位：fine 精细 / coarse 模糊
  photo_count INTEGER NOT NULL DEFAULT 0,
  time_start DATETIME,
  time_end DATETIME,
  hash_max INTEGER NOT NULL DEFAULT 0,     -- 组内最大相邻哈希距离
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
