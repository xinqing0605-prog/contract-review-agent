"""密码、会话令牌、密钥加密。

三个原则：
- 密码只存 PBKDF2 派生值，永远不存明文，比较用常量时间
- 会话只存令牌的 SHA-256，数据库泄露也不能直接拿来登录
- 用户填的 API Key 用 AES（Fernet）加密后落库，接口只返回掩码
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

# OWASP 对 PBKDF2-HMAC-SHA256 的建议量级是 60 万次
PBKDF2_ROUNDS = 600_000
LEGACY_ROUNDS = 240_000
COOKIE_NAME = "cg_session"
SESSION_DAYS = 7


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """哈希里带上迭代次数，方便以后调高而不影响老用户登录。"""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS
    )
    return f"{PBKDF2_ROUNDS}${digest.hex()}", salt


def verify_password(password: str, salt: str, expected: str) -> bool:
    rounds = LEGACY_ROUNDS
    stored = expected
    if "$" in expected:
        head, stored = expected.split("$", 1)
        try:
            rounds = int(head)
        except ValueError:
            return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds
    )
    return hmac.compare_digest(digest.hex(), stored)


def needs_rehash(expected: str) -> bool:
    """老哈希（没有迭代次数字段，或次数低于当前标准）应在下次登录时升级。"""
    if "$" not in expected:
        return True
    head, _ = expected.split("$", 1)
    try:
        return int(head) < PBKDF2_ROUNDS
    except ValueError:
        return True


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _fernet(data_dir: Path):
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("服务端缺少 cryptography，无法加密保存模型 Key") from exc

    secret = os.getenv("CLAUSEGUARD_SECRET", "").strip()
    if secret:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    else:
        key_file = data_dir / ".master.key"
        if key_file.exists():
            key = key_file.read_bytes().strip()
        else:
            data_dir.mkdir(parents=True, exist_ok=True)
            key = base64.urlsafe_b64encode(secrets.token_bytes(32))
            key_file.write_bytes(key)
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass  # Windows 上 chmod 语义有限，靠目录权限兜底
    return Fernet(key)


def encrypt_secret(value: str, data_dir: Path) -> str:
    return _fernet(data_dir).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(blob: str, data_dir: Path) -> str:
    return _fernet(data_dir).decrypt(blob.encode("ascii")).decode("utf-8")


def key_hint(value: str) -> str:
    """只留头尾，用于界面回显，绝不能反推出完整 Key。"""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-4:]}"
