"""注册 / 登录 / 会话。

账号支持**邮箱或用户名**：
- 含 `@` 视为邮箱（统一转小写）
- 否则视为用户名（3–20 位，中文/字母/数字/下划线/点/横线）

会话用 httpOnly Cookie + 服务端 session 表：
- 前端拿不到令牌，XSS 也偷不走
- 退出登录是真删记录
- 服务重启后会话仍然有效
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import db
from .security import (
    COOKIE_NAME,
    needs_rehash,
    SESSION_DAYS,
    hash_password,
    new_session_token,
    token_hash,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fa5.\-]{3,20}$")
MIN_PASSWORD = 8
SECURE_COOKIE = os.getenv("CLAUSEGUARD_SECURE_COOKIES", "0") == "1"

# 常见弱口令，直接拒绝
WEAK_PASSWORDS = {
    "12345678", "123456789", "1234567890", "password", "password1", "password123",
    "qwertyui", "qwerty123", "abc12345", "11111111", "88888888", "admin123",
    "iloveyou", "woaini1314", "a1234567", "abcd1234", "1qaz2wsx", "zaq12wsx",
    "p@ssw0rd", "letmein1", "welcome1", "monkey123", "dragon123",
}


def validate_password(password: str, account: str) -> None:
    """长度 + 字符类别 + 弱口令 + 与账号相关性。"""
    if len(password) < MIN_PASSWORD:
        raise HTTPException(422, f"密码至少 {MIN_PASSWORD} 位")

    classes = sum(
        [
            bool(re.search(r"[a-z]", password)),
            bool(re.search(r"[A-Z]", password)),
            bool(re.search(r"\d", password)),
            bool(re.search(r"[^A-Za-z0-9]", password)),
        ]
    )
    if classes < 3:
        raise HTTPException(422, "密码需包含大写字母、小写字母、数字、符号中的至少三类")

    if password.lower() in WEAK_PASSWORDS:
        raise HTTPException(422, "这个密码太常见了，换一个")

    handle = account.split("@")[0].lower()
    if len(handle) >= 3 and handle in password.lower():
        raise HTTPException(422, "密码不能包含账号名")

_FAILURES: dict[str, list[float]] = {}
MAX_FAILURES = 8
WINDOW_SECONDS = 600


class RegisterRequest(BaseModel):
    account: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=MIN_PASSWORD, max_length=128)
    name: str = Field(default="", max_length=40)


class LoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=128)


def _public_user(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "username": row["username"] if "username" in row.keys() else None,
        "name": row["name"],
    }


def _classify(account: str) -> tuple[str, str]:
    """返回 (类型, 规范化后的值)。"""
    value = account.strip()
    if "@" in value:
        return "email", value.lower()
    return "username", value.lower()


def _validate_account(kind: str, value: str) -> None:
    if kind == "email":
        if not EMAIL_RE.match(value):
            raise HTTPException(422, "邮箱格式不正确")
    else:
        if not USERNAME_RE.match(value):
            raise HTTPException(422, "用户名需 3–20 位，可用中文、字母、数字、下划线")


def _issue_session(user_id: str) -> str:
    token = new_session_token()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,datetime('now', ?))",
            (token_hash(token), user_id, f"+{SESSION_DAYS} days"),
        )
    return token


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=SECURE_COOKIE,
        path="/",
    )


@router.post("/register")
def register(body: RegisterRequest, response: Response) -> dict[str, Any]:
    kind, value = _classify(body.account)
    _validate_account(kind, value)
    validate_password(body.password, value)

    with db.tx() as conn:
        exists = conn.execute(
            "SELECT id FROM users WHERE email=? OR username=?", (value, value)
        ).fetchone()
        if exists:
            label = "邮箱" if kind == "email" else "用户名"
            raise HTTPException(409, f"这个{label}已经被注册了")

        digest, salt = hash_password(body.password)
        user_id = f"user-{int(time.time() * 1000)}"
        name = body.name.strip() or (value.split("@")[0] if kind == "email" else value)
        conn.execute(
            "INSERT INTO users(id,email,username,name,password_hash,password_salt,presets_seeded) "
            "VALUES(?,?,?,?,?,?,0)",
            (
                user_id,
                value if kind == "email" else None,
                value if kind == "username" else None,
                name,
                digest,
                salt,
            ),
        )
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    _set_cookie(response, _issue_session(user_id))
    return {"user": _public_user(row)}


@router.post("/login")
def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    _, value = _classify(body.account)
    now = time.time()
    recent = [stamp for stamp in _FAILURES.get(value, []) if now - stamp < WINDOW_SECONDS]
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(429, "失败次数过多，请 10 分钟后再试")
    _FAILURES[value] = recent

    with db.tx() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email=? OR username=?", (value, value)
        ).fetchone()

    if not row or not verify_password(body.password, row["password_salt"], row["password_hash"]):
        _FAILURES[value] = recent + [now]
        raise HTTPException(401, "账号或密码不正确")

    _FAILURES.pop(value, None)

    # 老哈希（迭代次数低）在登录成功时静默升级，用户无感
    if needs_rehash(row["password_hash"]):
        digest, _ = hash_password(body.password, row["password_salt"])
        with db.tx() as conn:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (digest, row["id"]))

    _set_cookie(response, _issue_session(row["id"]))
    return {"user": _public_user(row)}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with db.tx() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "logged_out"}


def current_user(request: Request) -> dict[str, Any]:
    """FastAPI 依赖：解析会话，失败一律 401。"""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "请先登录")
    with db.tx() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at > datetime('now')",
            (token_hash(token),),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE sessions SET last_seen_at=datetime('now') WHERE token_hash=?",
                (token_hash(token),),
            )
    if not row:
        raise HTTPException(401, "登录已过期，请重新登录")
    return _public_user(row)


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    return {"user": current_user(request)}
