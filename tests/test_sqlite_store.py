"""SQLite 存储后端与 JSON → SQLite 迁移（P2 · S4）。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from server import db, store


def test_default_backend_is_sqlite():
    assert store.backend() == "sqlite"


def test_schema_and_journal_mode():
    tables = {
        row["name"]
        for row in db._connect().execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"items", "shared", "schema_migrations"} <= tables
    assert db._connect().execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert db.applied_migrations(), "至少应用过一个迁移"


def test_migrations_are_idempotent():
    assert db.init() == [], "已应用的迁移不应重复执行"


def test_health_reports_store_backend(client):
    payload = client.get("/api/health").json()
    assert payload["store"] == "sqlite"
    assert payload["schema_version"] >= 1
    assert payload["db_size_kb"] >= 0


def test_item_roundtrip_with_derived_index_columns():
    item = {
        "id": "lsn_s4_demo",
        "created_at": 123.0,
        "teacher_id": "tc_demo_owner",
        "class_id": "cl_demo_parent",
        "title": "S4 验证",
    }
    store.save_item("lessons", item)
    row = db._connect().execute(
        "SELECT owner_id, parent_id, data FROM items WHERE collection='lessons' AND id='lsn_s4_demo'",
    ).fetchone()
    assert row["owner_id"] == "tc_demo_owner"
    assert row["parent_id"] == "cl_demo_parent"
    assert json.loads(row["data"])["title"] == "S4 验证"

    loaded = store.load_item("lessons", "lsn_s4_demo")
    assert loaded is not None and loaded["title"] == "S4 验证"
    loaded["title"] = "改了副本"
    assert store.load_item("lessons", "lsn_s4_demo")["title"] == "S4 验证"

    assert store.delete_item("lessons", "lsn_s4_demo") is True
    assert store.delete_item("lessons", "lsn_s4_demo") is False
    assert store.load_item("lessons", "lsn_s4_demo") is None


def test_rejects_unknown_collection_and_bad_id():
    with pytest.raises(ValueError):
        store.load_item("nope", "x1")
    with pytest.raises(ValueError):
        store.load_item("lessons", "../etc/passwd")


def test_import_from_json_then_rerun_is_noop(tmp_path):
    (tmp_path / "lessons").mkdir()
    (tmp_path / "lessons" / "lsn_mig1.json").write_text(
        json.dumps({"id": "lsn_mig1", "created_at": 3, "title": "迁移"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "progress.json").write_text(json.dumps({"topics": {}, "events": []}), encoding="utf-8")

    first = db.import_from_json(["lessons"], ["progress"], data_dir=tmp_path, apply=True)
    assert first["items"]["lessons"] == 1
    assert first["shared"]["progress"] == 1
    assert first["verified"] and not first["errors"]
    assert store.load_item("lessons", "lsn_mig1")["title"] == "迁移"

    second = db.import_from_json(["lessons"], ["progress"], data_dir=tmp_path, apply=True)
    assert second["items"]["lessons"] == 0
    assert second["skipped"] == 1
    assert second["verified"]

    store.delete_item("lessons", "lsn_mig1")


def test_dry_run_writes_nothing(tmp_path):
    (tmp_path / "lessons").mkdir()
    (tmp_path / "lessons" / "lsn_dry_run.json").write_text(
        json.dumps({"id": "lsn_dry_run", "title": "只看不写"}), encoding="utf-8",
    )
    stats = db.import_from_json(["lessons"], [], data_dir=tmp_path, apply=False)
    assert stats["items"]["lessons"] == 1
    assert store.load_item("lessons", "lsn_dry_run") is None


def test_json_backend_fallback(monkeypatch):
    """EDU_STORE=json 时退回原来的 JSON 文件，行为保持一致。"""
    monkeypatch.setattr(store, "_BACKEND", "json")
    assert store.backend() == "json"
    store.save_item("lessons", {"id": "lsn_json_fb", "title": "回退"})
    path = Path(os.environ["EDU_DATA_DIR"]) / "lessons" / "lsn_json_fb.json"
    assert path.is_file(), "JSON 后端应把数据写回文件"
    assert store.load_item("lessons", "lsn_json_fb")["title"] == "回退"
    assert store.delete_item("lessons", "lsn_json_fb") is True
    assert not path.exists()
