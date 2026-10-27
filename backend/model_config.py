"""模型服务：服务商只是分组，地址与 Key 挂在「模型」上。

- model_services：名称 + 类型（大模型 / 综合服务 / 本地模型…）
- service_models：模型标识 + 接口地址 + API Key + 说明，可单独启用
- 审阅时使用「当前使用」的那个模型

安全：
1. Key 加密落库，接口只回显掩码
2. base_url 由服务端请求，必须挡掉内网地址（SSRF）
3. Key 与地址绑定：改地址又没有新 Key 时拒绝，避免把旧 Key 发往别处
"""
from __future__ import annotations

import ipaddress
import os
import socket
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import db, llm_stats, provider
from .auth import current_user
from .security import decrypt_secret, encrypt_secret, key_hint

router = APIRouter(prefix="/api/settings", tags=["settings"])

ALLOW_PRIVATE = os.getenv("CLAUSEGUARD_ALLOW_PRIVATE_MODEL", "1") == "1"
PRIVATE_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
KINDS = ["大模型", "综合服务", "本地模型", "自定义"]


class ServiceInput(BaseModel):
    name: str = Field(default="", max_length=60)
    kind: str = Field(default="大模型", max_length=20)


class ModelInput(BaseModel):
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=120)
    base_url: str = Field(default="", max_length=300)
    api_key: str = Field(default="", max_length=400)


class PresetInput(BaseModel):
    label: str = Field(default="", max_length=60)
    base_url: str = Field(default="", max_length=300)


def validate_base_url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(422, "地址必须以 http:// 或 https:// 开头")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise HTTPException(422, "地址缺少域名")
    if host in PRIVATE_HOSTS or host.endswith(".local"):
        if not ALLOW_PRIVATE:
            raise HTTPException(422, "服务端已禁止访问内网地址")
        return url
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(422, f"域名解析失败：{host}") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            if not ALLOW_PRIVATE:
                raise HTTPException(422, "该地址解析到内网，已拒绝")
    if parsed.scheme != "https":
        raise HTTPException(422, "公网地址必须使用 https")
    return url


def _decrypt(blob: str) -> str:
    if not blob:
        return ""
    try:
        return decrypt_secret(blob, db.DATA_DIR)
    except Exception:
        return ""


def list_presets(user_id: str) -> list[dict[str, Any]]:
    db.ensure_presets(user_id)
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT id,label,base_url FROM service_presets WHERE user_id=? ORDER BY created_at",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_services(user_id: str) -> list[dict[str, Any]]:
    with db.tx() as conn:
        services = conn.execute(
            "SELECT * FROM model_services WHERE user_id=? ORDER BY created_at", (user_id,)
        ).fetchall()
        models = conn.execute(
            "SELECT * FROM service_models WHERE user_id=? ORDER BY created_at", (user_id,)
        ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in models:
        grouped.setdefault(row["service_id"], []).append(
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"] or "",
                "base_url": row["base_url"] or "",
                "key_hint": row["key_hint"] or "",
                "configured": bool(row["api_key_enc"]),
                "is_active": bool(row["is_active"]),
                "verified_at": row["verified_at"],
            }
        )

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"] or "大模型",
            "models": grouped.get(row["id"], []),
        }
        for row in services
    ]


def load_config(user_id: str) -> dict[str, Any] | None:
    """审阅用：当前使用的模型（含地址与 Key）。函数名保持不变，app.py 无需改动。"""
    with db.tx() as conn:
        row = conn.execute(
            "SELECT m.base_url, m.api_key_enc, m.name AS model, s.name AS service "
            "FROM service_models m JOIN model_services s ON s.id = m.service_id "
            "WHERE m.user_id=? AND m.is_active=1 LIMIT 1",
            (user_id,),
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT m.base_url, m.api_key_enc, m.name AS model, s.name AS service "
                "FROM service_models m JOIN model_services s ON s.id = m.service_id "
                "WHERE m.user_id=? ORDER BY m.created_at LIMIT 1",
                (user_id,),
            ).fetchone()
    if not row:
        return None
    return {
        "base_url": row["base_url"],
        "model": row["model"],
        "name": row["service"],
        "api_key": _decrypt(row["api_key_enc"]),
    }


def _service_or_404(service_id: str, user_id: str) -> Any:
    with db.tx() as conn:
        row = conn.execute(
            "SELECT * FROM model_services WHERE id=? AND user_id=?", (service_id, user_id)
        ).fetchone()
    if not row:
        raise HTTPException(404, "service not found")
    return row


def _model_or_404(service_id: str, model_id: str, user_id: str) -> Any:
    with db.tx() as conn:
        row = conn.execute(
            "SELECT * FROM service_models WHERE id=? AND service_id=? AND user_id=?",
            (model_id, service_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "model not found")
    return row


def _promote_first(conn: Any, user_id: str) -> None:
    """没有任何启用模型时，启用最早的那个，避免审阅拿不到配置。"""
    row = conn.execute(
        "SELECT COUNT(*) FROM service_models WHERE user_id=? AND is_active=1", (user_id,)
    ).fetchone()[0]
    if row:
        return
    first = conn.execute(
        "SELECT id FROM service_models WHERE user_id=? ORDER BY created_at LIMIT 1", (user_id,)
    ).fetchone()
    if first:
        conn.execute("UPDATE service_models SET is_active=1 WHERE id=?", (first["id"],))


# --------------------------------------------------------------------------- 服务商
@router.get("/services")
def read_services(user: dict = Depends(current_user)) -> dict[str, Any]:
    return {
        "services": list_services(user["id"]),
        "presets": list_presets(user["id"]),
        "kinds": KINDS,
    }


@router.post("/services")
def create_service(body: ServiceInput, user: dict = Depends(current_user)) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "请填写服务商名称")
    with db.tx() as conn:
        exists = conn.execute(
            "SELECT id FROM model_services WHERE user_id=? AND name=?", (user["id"], name)
        ).fetchone()
        if exists:
            raise HTTPException(409, f"已经有同名服务商「{name}」")
        conn.execute(
            "INSERT INTO model_services(id,user_id,name,kind,created_at,updated_at) "
            "VALUES(?,?,?,?,datetime('now'),datetime('now'))",
            (f"svc-{uuid.uuid4().hex[:10]}", user["id"], name, body.kind.strip() or "大模型"),
        )
    return {"services": list_services(user["id"])}


@router.put("/services/{service_id}")
def update_service(
    service_id: str, body: ServiceInput, user: dict = Depends(current_user)
) -> dict[str, Any]:
    _service_or_404(service_id, user["id"])
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "请填写服务商名称")
    with db.tx() as conn:
        exists = conn.execute(
            "SELECT id FROM model_services WHERE user_id=? AND name=? AND id<>?",
            (user["id"], name, service_id),
        ).fetchone()
        if exists:
            raise HTTPException(409, f"已经有同名服务商「{name}」")
        conn.execute(
            "UPDATE model_services SET name=?, kind=?, updated_at=datetime('now') "
            "WHERE id=? AND user_id=?",
            (name, body.kind.strip() or "大模型", service_id, user["id"]),
        )
    return {"services": list_services(user["id"])}


@router.delete("/services/{service_id}")
def delete_service(service_id: str, user: dict = Depends(current_user)) -> dict[str, Any]:
    _service_or_404(service_id, user["id"])
    with db.tx() as conn:
        conn.execute("DELETE FROM service_models WHERE service_id=?", (service_id,))
        conn.execute(
            "DELETE FROM model_services WHERE id=? AND user_id=?", (service_id, user["id"])
        )
        _promote_first(conn, user["id"])
    return {"services": list_services(user["id"])}


# --------------------------------------------------------------------------- 模型
@router.post("/services/{service_id}/models")
def create_model(
    service_id: str, body: ModelInput, user: dict = Depends(current_user)
) -> dict[str, Any]:
    _service_or_404(service_id, user["id"])
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "请填写模型标识")
    base_url = validate_base_url(body.base_url) if body.base_url.strip() else ""
    if not base_url:
        raise HTTPException(422, "请填写完整接口地址")
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(422, "请填写 API Key")
    if len(api_key) < 8:
        raise HTTPException(422, "API Key 看起来不完整，请检查是否复制全")

    try:
        with db.tx() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM service_models WHERE user_id=?", (user["id"],)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO service_models"
                "(id,service_id,user_id,name,description,base_url,api_key_enc,key_hint,"
                "is_active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
                (
                    f"mdl-{uuid.uuid4().hex[:10]}",
                    service_id,
                    user["id"],
                    name,
                    body.description.strip(),
                    base_url,
                    encrypt_secret(api_key, db.DATA_DIR) if api_key else "",
                    key_hint(api_key) if api_key else "",
                    0 if count else 1,
                ),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(409, f"这个服务商下已经有模型「{name}」") from None
        raise
    return {"services": list_services(user["id"])}


@router.put("/services/{service_id}/models/{model_id}")
def update_model(
    service_id: str, model_id: str, body: ModelInput, user: dict = Depends(current_user)
) -> dict[str, Any]:
    row = _model_or_404(service_id, model_id, user["id"])
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "请填写模型标识")
    base_url = validate_base_url(body.base_url) if body.base_url.strip() else ""
    if not base_url:
        raise HTTPException(422, "请填写完整接口地址")

    api_key = body.api_key.strip()
    if row["base_url"] != base_url and not api_key:
        raise HTTPException(409, "修改了接口地址，请重新填写 API Key")

    encrypted = row["api_key_enc"] or ""
    hint = row["key_hint"] or ""
    if api_key:
        encrypted = encrypt_secret(api_key, db.DATA_DIR)
        hint = key_hint(api_key)

    try:
        with db.tx() as conn:
            conn.execute(
                "UPDATE service_models SET name=?, description=?, base_url=?, api_key_enc=?, "
                "key_hint=?, updated_at=datetime('now'), verified_at=NULL "
                "WHERE id=? AND service_id=? AND user_id=?",
                (
                    name,
                    body.description.strip(),
                    base_url,
                    encrypted,
                    hint,
                    model_id,
                    service_id,
                    user["id"],
                ),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(409, f"已经有同名模型「{name}」") from None
        raise
    return {"services": list_services(user["id"])}


@router.delete("/services/{service_id}/models/{model_id}")
def delete_model(service_id: str, model_id: str, user: dict = Depends(current_user)) -> dict[str, Any]:
    _model_or_404(service_id, model_id, user["id"])
    with db.tx() as conn:
        conn.execute("DELETE FROM service_models WHERE id=?", (model_id,))
        _promote_first(conn, user["id"])
    return {"services": list_services(user["id"])}


@router.post("/services/{service_id}/models/{model_id}/activate")
def activate_model(
    service_id: str, model_id: str, user: dict = Depends(current_user)
) -> dict[str, Any]:
    _model_or_404(service_id, model_id, user["id"])
    with db.tx() as conn:
        conn.execute("UPDATE service_models SET is_active=0 WHERE user_id=?", (user["id"],))
        conn.execute("UPDATE service_models SET is_active=1 WHERE id=?", (model_id,))
    return {"services": list_services(user["id"])}


@router.post("/services/{service_id}/models/{model_id}/test")
def test_model(
    service_id: str, model_id: str, user: dict = Depends(current_user)
) -> dict[str, Any]:
    row = _model_or_404(service_id, model_id, user["id"])
    api_key = _decrypt(row["api_key_enc"])
    if not api_key:
        raise HTTPException(409, "这个模型还没有填写 API Key")
    started = time.perf_counter()
    try:
        result, meta = provider.complete_json(
            {"base_url": row["base_url"], "model": row["name"], "api_key": api_key},
            '这是连接验证，请返回 {"ok": true}。',
            {"task": "connection_check"},
            max_tokens=64,
        )
    except HTTPException as exc:
        llm_stats.record(
            user_id=user["id"],
            purpose="connection_check",
            model=str(row["name"] or ""),
            base_url=str(row["base_url"] or ""),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            ok=False,
            error=str(exc.detail),
        )
        raise HTTPException(502, str(exc.detail)) from None
    if result.get("ok") is not True:
        llm_stats.record(
            user_id=user["id"],
            purpose="connection_check",
            model=str(row["name"] or ""),
            base_url=str(row["base_url"] or ""),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            ok=False,
            error="模型返回内容不符合 JSON 格式要求",
        )
        raise HTTPException(502, "模型返回了内容，但不符合 JSON 格式要求")
    llm_stats.record(
        user_id=user["id"],
        purpose="connection_check",
        model=str(meta.get("model") or row["name"] or ""),
        base_url=str(row["base_url"] or ""),
        usage=meta.get("usage") or {},
        duration_ms=float(meta.get("duration_ms") or 0),
        ok=True,
    )
    with db.tx() as conn:
        conn.execute(
            "UPDATE service_models SET verified_at=datetime('now') WHERE id=?", (model_id,)
        )
    return {
        "ok": True,
        "model": meta.get("model", row["name"]),
        "duration_ms": meta.get("duration_ms"),
        "services": list_services(user["id"]),
    }


# --------------------------------------------------------------------------- 模板
@router.get("/presets")
def read_presets(user: dict = Depends(current_user)) -> dict[str, Any]:
    return {"presets": list_presets(user["id"])}


@router.post("/presets")
def create_preset(body: PresetInput, user: dict = Depends(current_user)) -> dict[str, Any]:
    label = body.label.strip()
    base_url = body.base_url.strip().rstrip("/")
    if not label or not base_url:
        raise HTTPException(422, "模板名称和 Base URL 都不能为空")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO service_presets(id,user_id,label,base_url) VALUES(?,?,?,?)",
            (f"preset-{uuid.uuid4().hex[:10]}", user["id"], label, base_url),
        )
    return {"presets": list_presets(user["id"])}


@router.put("/presets/{preset_id}")
def update_preset(
    preset_id: str, body: PresetInput, user: dict = Depends(current_user)
) -> dict[str, Any]:
    label = body.label.strip()
    base_url = body.base_url.strip().rstrip("/")
    if not label or not base_url:
        raise HTTPException(422, "模板名称和 Base URL 都不能为空")
    with db.tx() as conn:
        row = conn.execute(
            "SELECT id FROM service_presets WHERE id=? AND user_id=?", (preset_id, user["id"])
        ).fetchone()
        if not row:
            raise HTTPException(404, "preset not found")
        conn.execute(
            "UPDATE service_presets SET label=?, base_url=? WHERE id=? AND user_id=?",
            (label, base_url, preset_id, user["id"]),
        )
    return {"presets": list_presets(user["id"])}


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: str, user: dict = Depends(current_user)) -> dict[str, Any]:
    with db.tx() as conn:
        row = conn.execute(
            "SELECT * FROM service_presets WHERE id=? AND user_id=?", (preset_id, user["id"])
        ).fetchone()
        if not row:
            raise HTTPException(404, "preset not found")
        conn.execute(
            "DELETE FROM service_presets WHERE id=? AND user_id=?", (preset_id, user["id"])
        )
    return {"presets": list_presets(user["id"])}
