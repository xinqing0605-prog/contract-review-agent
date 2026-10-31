"""语义召回设置：选一个向量模型、设定相似度阈值、开关。

复用「服务商 → 模型」的既有结构，不重复保存 Key：
用户需要先在「模型设置」里添加一个支持 /embeddings 的模型
（如通义 text-embedding-v3、OpenAI text-embedding-3-small、BAAI/bge-m3），
再到「语义召回」里选中它。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import db, semantic
from .auth import current_user
from .security import decrypt_secret

router = APIRouter(prefix="/api/settings/recall", tags=["recall"])

DEFAULT_THRESHOLD = semantic.DEFAULT_THRESHOLD
MIN_THRESHOLD = semantic.MIN_THRESHOLD
MAX_THRESHOLD = semantic.MAX_THRESHOLD


class RecallSettingsInput(BaseModel):
    enabled: bool = False
    model_id: str = ""
    threshold: float = Field(default=DEFAULT_THRESHOLD, ge=MIN_THRESHOLD, le=MAX_THRESHOLD)


def load(user_id: str) -> dict[str, Any]:
    with db.tx() as conn:
        row = conn.execute(
            "SELECT model_id, threshold, enabled FROM embedding_settings WHERE user_id=?",
            (user_id,),
        ).fetchone()
    if row is None:
        return {"enabled": False, "model_id": "", "threshold": DEFAULT_THRESHOLD}
    return {
        "enabled": bool(row["enabled"]),
        "model_id": row["model_id"] or "",
        "threshold": float(row["threshold"] or DEFAULT_THRESHOLD),
    }


def available_models(user_id: str) -> list[dict[str, Any]]:
    """当前用户已配置 Key 的模型，供下拉选择；capability 供前端过滤。"""
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT m.id, m.name, m.base_url, m.api_key_enc, m.capability, s.name AS service_name "
            "FROM service_models m JOIN model_services s ON s.id = m.service_id "
            "WHERE m.user_id=? ORDER BY s.name, m.name",
            (user_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "base_url": row["base_url"],
            "service": row["service_name"],
            "configured": bool(row["api_key_enc"]),
            "capability": row["capability"] or "",
        }
        for row in rows
    ]


def resolve_config(user_id: str) -> dict[str, Any] | None:
    """把设置解析成可直接调用的连接配置；未启用或模型缺失时返回 None。"""
    settings = load(user_id)
    if not settings["enabled"] or not settings["model_id"]:
        return None
    with db.tx() as conn:
        row = conn.execute(
            "SELECT name, base_url, api_key_enc FROM service_models WHERE id=? AND user_id=?",
            (settings["model_id"], user_id),
        ).fetchone()
    if row is None or not row["api_key_enc"]:
        return None
    try:
        api_key = decrypt_secret(row["api_key_enc"], db.DATA_DIR)
    except Exception:  # noqa: BLE001
        return None
    if not api_key:
        return None
    return {"base_url": row["base_url"], "model": row["name"], "api_key": api_key}


def _view(user_id: str) -> dict[str, Any]:
    return {
        "settings": load(user_id),
        "models": available_models(user_id),
        "bounds": {"min": MIN_THRESHOLD, "max": MAX_THRESHOLD, "default": DEFAULT_THRESHOLD},
    }


@router.post("/probe")
def probe(body: RecallSettingsInput, user: dict = Depends(current_user)) -> dict[str, Any]:
    """用指定模型逐个尝试向量请求格式，返回每种格式的结果（不落库、不写缓存）。"""
    model_id = body.model_id.strip()
    if not model_id:
        raise HTTPException(409, "请先选择一个向量模型")
    models = {item["id"]: item for item in available_models(user["id"])}
    target = models.get(model_id)
    if target is None:
        raise HTTPException(404, "选择的模型不存在")
    if not target["configured"]:
        raise HTTPException(409, "该模型还没有填写 API Key")
    with db.tx() as conn:
        row = conn.execute(
            "SELECT name, base_url, api_key_enc FROM service_models WHERE id=? AND user_id=?",
            (model_id, user["id"]),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "选择的模型不存在")
    try:
        api_key = decrypt_secret(row["api_key_enc"], db.DATA_DIR)
    except Exception:  # noqa: BLE001
        raise HTTPException(409, "无法解密该模型的 API Key，请重新填写") from None

    from .embeddings import probe_formats

    results = probe_formats(
        {"base_url": row["base_url"], "model": row["name"], "api_key": api_key}
    )
    return {"model": row["name"], "results": results}


@router.get("")
def read_settings(user: dict = Depends(current_user)) -> dict[str, Any]:
    return _view(user["id"])


@router.put("")
def save_settings(body: RecallSettingsInput, user: dict = Depends(current_user)) -> dict[str, Any]:
    model_id = body.model_id.strip()
    if body.enabled:
        if not model_id:
            raise HTTPException(409, "开启语义召回前请先选择一个向量模型")
        models = {item["id"]: item for item in available_models(user["id"])}
        target = models.get(model_id)
        if target is None:
            raise HTTPException(404, "选择的模型不存在")
        if not target["configured"]:
            raise HTTPException(409, "该模型还没有填写 API Key")

    with db.tx() as conn:
        conn.execute(
            "INSERT INTO embedding_settings(user_id, model_id, threshold, enabled, updated_at) "
            "VALUES(?,?,?,?,datetime('now')) "
            "ON CONFLICT(user_id) DO UPDATE SET model_id=excluded.model_id, "
            "threshold=excluded.threshold, enabled=excluded.enabled, updated_at=datetime('now')",
            (user["id"], model_id, float(body.threshold), 1 if body.enabled else 0),
        )
    return _view(user["id"])
