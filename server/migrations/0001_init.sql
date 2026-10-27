-- 0001：初始结构。
-- items 是「泛化表」：业务字段整体进 data(JSON)，其余列都是为了索引和排序。
CREATE TABLE IF NOT EXISTS items (
    collection TEXT NOT NULL,
    id         TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT 0,
    owner_id   TEXT,
    parent_id  TEXT,
    data       TEXT NOT NULL,
    PRIMARY KEY (collection, id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_items_created ON items(collection, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_owner   ON items(collection, owner_id);
CREATE INDEX IF NOT EXISTS idx_items_parent  ON items(collection, parent_id);

-- 共享 KV（progress / sessions / agents），和原来 data/*.json 一一对应。
CREATE TABLE IF NOT EXISTS shared (
    name       TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at REAL NOT NULL
) WITHOUT ROWID;
