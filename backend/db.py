"""数据库：连接、建表、迁移、演示数据。

模型配置是两层结构：
- model_services   服务商：名称 + base_url + Key（同一个服务商只存一份 Key）
- service_models   该服务商下的模型：只存模型名，可以有很多个
- service_presets  用户自己的服务商模板（只有名称 + 地址，不再带模型）

审阅时取「当前使用的服务商」+ 它下面「当前使用的模型」。
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from .security import hash_password

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent

DB_PATH = Path(os.getenv("CLAUSEGUARD_DB") or (BACKEND_DIR / "clauseguard.sqlite3"))
DATA_DIR = Path(os.getenv("CLAUSEGUARD_DATA") or (ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"

DEMO_EMAIL = "demo@clauseguard.local"
DEMO_PASSWORD = "demo1234"
DEMO_USER_ID = "user-demo"

# 首次访问时给每个用户灌一份；之后完全由用户自己增删改
DEFAULT_PRESETS = [
    ("DeepSeek", "https://api.deepseek.com"),
    ("Moonshot / Kimi", "https://api.moonshot.cn/v1"),
    ("智谱 GLM", "https://open.bigmodel.cn/api/paas/v4"),
    ("阿里通义 / Qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ("OpenAI", "https://api.openai.com/v1"),
    ("OpenRouter", "https://openrouter.ai/api/v1"),
    ("SiliconFlow", "https://api.siliconflow.cn/v1"),
    ("本地 Ollama", "http://127.0.0.1:11434/v1"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE,
  username TEXT UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  presets_seeded INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  expires_at TEXT NOT NULL,
  last_seen_at TEXT);

CREATE TABLE IF NOT EXISTS service_presets(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  label TEXT NOT NULL,
  base_url TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS model_services(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT '大模型',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT);

CREATE TABLE IF NOT EXISTS service_models(
  id TEXT PRIMARY KEY,
  service_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  base_url TEXT NOT NULL DEFAULT '',
  api_key_enc TEXT DEFAULT '',
  key_hint TEXT DEFAULT '',
  is_active INTEGER DEFAULT 0,
  verified_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT,
  UNIQUE(service_id, name));

CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY,
  user_id TEXT,
  name TEXT,
  owner TEXT,
  text TEXT,
  status TEXT DEFAULT 'pending',
  source_type TEXT DEFAULT 'text',
  file_path TEXT,
  deleted INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS clauses(
  id TEXT PRIMARY KEY,
  document_id TEXT,
  title TEXT,
  risk TEXT,
  excerpt TEXT,
  original TEXT,
  reason TEXT,
  recommend TEXT,
  start_offset INTEGER,
  end_offset INTEGER,
  accepted INTEGER DEFAULT 0,
  comment TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  reject_reason TEXT DEFAULT '',
  approved_at TEXT,
  executed_at TEXT,
  updated_at TEXT);

CREATE TABLE IF NOT EXISTS idempotency_keys(
  key TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  action TEXT NOT NULL,
  response TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS review_audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT,
  user_id TEXT,
  action TEXT,
  payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS llm_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  document_id TEXT,
  purpose TEXT NOT NULL DEFAULT 'review',
  model TEXT DEFAULT '',
  base_url TEXT DEFAULT '',
  prompt_tokens INTEGER DEFAULT 0,
  completion_tokens INTEGER DEFAULT 0,
  total_tokens INTEGER DEFAULT 0,
  duration_ms REAL DEFAULT 0,
  ok INTEGER DEFAULT 1,
  error TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE INDEX IF NOT EXISTS idx_llm_calls_user_time ON llm_calls(user_id, created_at);

CREATE TABLE IF NOT EXISTS embedding_settings(
  user_id TEXT PRIMARY KEY,
  model_id TEXT DEFAULT '',
  threshold REAL DEFAULT 0.82,
  enabled INTEGER DEFAULT 0,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS embedding_cache(
  key TEXT PRIMARY KEY,
  model TEXT NOT NULL,
  vector TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _migrate_flat_providers(conn: sqlite3.Connection) -> None:
    """把 v6 的「一条记录 = 一个服务商 + 一个模型」迁移成两层结构。"""
    if "model_providers" not in _tables(conn):
        return

    services: dict[tuple[str, str], str] = {}
    rows = conn.execute("SELECT * FROM model_providers ORDER BY created_at").fetchall()
    for row in rows:
        key = (row["user_id"], row["base_url"])
        service_id = services.get(key)
        if not service_id:
            service_id = f"svc-{uuid.uuid4().hex[:10]}"
            services[key] = service_id
            conn.execute(
                "INSERT INTO model_services"
                "(id,user_id,name,base_url,api_key_enc,key_hint,is_active,created_at,updated_at,verified_at) "
                "VALUES(?,?,?,?,?,?,?,datetime('now'),datetime('now'),?)",
                (
                    service_id,
                    row["user_id"],
                    row["name"],
                    row["base_url"],
                    row["api_key_enc"] or "",
                    row["key_hint"] or "",
                    1 if row["is_active"] else 0,
                    row["verified_at"],
                ),
            )
        conn.execute(
            "INSERT OR IGNORE INTO service_models(id,service_id,user_id,name,is_active) "
            "VALUES(?,?,?,?,?)",
            (
                f"mdl-{uuid.uuid4().hex[:10]}",
                service_id,
                row["user_id"],
                row["model"],
                1 if row["is_active"] else 0,
            ),
        )
    conn.execute("DROP TABLE model_providers")

    if "provider_presets" in _tables(conn):
        for row in conn.execute("SELECT * FROM provider_presets").fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO service_presets(id,user_id,label,base_url) VALUES(?,?,?,?)",
                (row["id"], row["user_id"], row["label"], row["base_url"]),
            )
        conn.execute("DROP TABLE provider_presets")


def _migrate(conn: sqlite3.Connection) -> None:
    """老库升级：只加列/表，不动已有业务数据。"""
    document_columns = _columns(conn, "documents")
    for name, ddl in (
        ("user_id", "TEXT"),
        ("source_type", "TEXT DEFAULT 'text'"),
        ("file_path", "TEXT"),
        ("deleted", "INTEGER DEFAULT 0"),
    ):
        if name not in document_columns:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {ddl}")

    clause_columns = _columns(conn, "clauses")
    for name, ddl in (
        ("comment", "TEXT DEFAULT ''"),
        ("updated_at", "TEXT"),
        ("status", "TEXT DEFAULT 'pending'"),
        ("reject_reason", "TEXT DEFAULT ''"),
        ("approved_at", "TEXT"),
        ("executed_at", "TEXT"),
    ):
        if name not in clause_columns:
            conn.execute(f"ALTER TABLE clauses ADD COLUMN {name} {ddl}")

    audit_columns = _columns(conn, "review_audit")
    if "user_id" not in audit_columns:
        conn.execute("ALTER TABLE review_audit ADD COLUMN user_id TEXT")

    user_columns = _columns(conn, "users")
    if "presets_seeded" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN presets_seeded INTEGER DEFAULT 0")

    # v1 的单套配置表直接丢弃，避免与新结构混用
    tables = _tables(conn)
    if "model_configs" in tables:
        conn.execute("DROP TABLE model_configs")

    _migrate_flat_providers(conn)
    _migrate_model_shape(conn)
    _migrate_users(conn)


def _migrate_model_shape(conn: sqlite3.Connection) -> None:
    """v7 把地址/Key 放在服务商上；改为「服务商只是分组，地址/Key 挂在模型上」。"""
    if "model_services" not in _tables(conn):
        return
    if "kind" in _columns(conn, "model_services"):
        return

    services = [dict(row) for row in conn.execute("SELECT * FROM model_services")]
    models = [dict(row) for row in conn.execute("SELECT * FROM service_models")]
    conn.execute("DROP TABLE IF EXISTS service_models")
    conn.execute("DROP TABLE IF EXISTS model_services")
    conn.executescript(
        """
CREATE TABLE model_services(
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT '大模型',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT);
CREATE TABLE service_models(
  id TEXT PRIMARY KEY, service_id TEXT NOT NULL, user_id TEXT NOT NULL,
  name TEXT NOT NULL, description TEXT DEFAULT '', base_url TEXT NOT NULL DEFAULT '',
  api_key_enc TEXT DEFAULT '', key_hint TEXT DEFAULT '', is_active INTEGER DEFAULT 0,
  verified_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT,
  UNIQUE(service_id, name));
"""
    )
    for service in services:
        conn.execute(
            "INSERT INTO model_services(id,user_id,name,kind,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                service["id"],
                service["user_id"],
                service["name"],
                "大模型",
                service["created_at"],
                service["updated_at"],
            ),
        )
    for model in models:
        parent = next((item for item in services if item["id"] == model["service_id"]), None)
        if not parent:
            continue
        conn.execute(
            "INSERT INTO service_models"
            "(id,service_id,user_id,name,description,base_url,api_key_enc,key_hint,"
            "is_active,verified_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                model["id"],
                model["service_id"],
                model["user_id"],
                model["name"],
                "",
                parent["base_url"],
                parent["api_key_enc"] or "",
                parent["key_hint"] or "",
                model["is_active"],
                parent["verified_at"],
                model["created_at"],
            ),
        )


def _migrate_users(conn) -> None:
    """老库的 users 没有 username，且 email 不允许为空 —— 重建这张表。"""
    if "username" in _columns(conn, "users"):
        return
    conn.executescript(
        """
CREATE TABLE users_new(
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE,
  username TEXT UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  presets_seeded INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
INSERT INTO users_new(id,email,username,name,password_hash,password_salt,presets_seeded,created_at)
  SELECT id,email,NULL,name,password_hash,password_salt,COALESCE(presets_seeded,0),created_at FROM users;
DROP TABLE users;
ALTER TABLE users_new RENAME TO users;
"""
    )


def ensure_presets(user_id: str) -> None:
    """每个用户首次访问时灌一份默认模板。用户删光了也不会自动补回来。"""
    with tx() as conn:
        row = conn.execute("SELECT presets_seeded FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None or row["presets_seeded"]:
            return
        conn.executemany(
            "INSERT INTO service_presets(id,user_id,label,base_url) VALUES(?,?,?,?)",
            [
                (f"preset-{user_id}-{index}", user_id, label, base_url)
                for index, (label, base_url) in enumerate(DEFAULT_PRESETS)
            ],
        )
        conn.execute("UPDATE users SET presets_seeded=1 WHERE id=?", (user_id,))


SAMPLE_DOCUMENTS = [
    (
        "contract-01",
        "供应商服务合同",
        "采购部",
        "甲方在收到乙方发票并验收合格后九十日内支付全部款项，逾期付款不承担利息或其他责任。"
        "乙方在任何情况下不对间接损失、预期利润损失、数据损失承担责任。"
        "任一方未在合同期限届满前三十日书面通知终止的，本合同自动续期一年。"
        "双方对保密信息的保护义务在本合同终止后继续有效两年。",
    ),
    (
        "contract-02",
        "渠道合作协议",
        "市场部",
        "合作期限内，甲方不得与任何同类渠道签署类似合作协议。"
        "乙方可基于合作产生的数据进行分析、优化和营销使用。",
    ),
    (
        "contract-03",
        "软件采购订单",
        "信息化部",
        "乙方保证服务可用性达到百分之九十九。乙方保留通用软件组件及基础工具的所有权。",
    ),
]


def seed() -> None:
    with tx() as conn:
        has_user = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
        if not has_user:
            digest, salt = hash_password(DEMO_PASSWORD)
            conn.execute(
                "INSERT INTO users(id,email,name,password_hash,password_salt,presets_seeded) "
                "VALUES(?,?,?,?,?,0)",
                (DEMO_USER_ID, DEMO_EMAIL, "演示账号", digest, salt),
            )
        if conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO documents(id,user_id,name,owner,text,source_type) VALUES(?,?,?,?,?, 'text')",
                [
                    (doc_id, DEMO_USER_ID, name, owner, text)
                    for doc_id, name, owner, text in SAMPLE_DOCUMENTS
                ],
            )
        else:
            conn.execute(
                "UPDATE documents SET user_id=? WHERE user_id IS NULL OR user_id=''",
                (DEMO_USER_ID,),
            )
            conn.execute(
                "UPDATE review_audit SET user_id=? WHERE user_id IS NULL OR user_id=''",
                (DEMO_USER_ID,),
            )


def init() -> None:
    with tx() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
    seed()
