-- S6：审计表。只追加、不修改；读取按时间倒序取最近 N 条。
CREATE TABLE IF NOT EXISTS audit (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  at         REAL NOT NULL,
  actor_id   TEXT,
  actor_name TEXT,
  action     TEXT NOT NULL,
  target     TEXT,
  result     TEXT,
  ip         TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_at ON audit(at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit(actor_id, at DESC);
