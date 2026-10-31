"""OpenAI 兼容的向量接口（/embeddings）客户端 + SQLite 缓存。

只依赖标准库，与 provider.py 保持一致的错误处理风格：
- 服务商不支持 /embeddings 时给出明确提示
- 超时与网络错误统一转 504
- 响应用量（usage）原样返回，交给 llm_stats 记录

缓存以 (model, base_url, text) 的 sha256 为键，避免重复计费：
同一份合同反复审阅、样本库每次都要算，不缓存会白白烧钱。
"""
from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
from typing import Any
from urllib import error, request

from fastapi import HTTPException

from . import db

TIMEOUT_SECONDS = 60
MAX_RESPONSE_BYTES = 8_000_000
BATCH_SIZE = 32
MAX_TEXTS = 400


def endpoint_of(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/embeddings"):
        return base
    return base + "/embeddings"


def cache_key(model: str, base_url: str, text: str) -> str:
    payload = f"{base_url.rstrip('/')}\n{model}\n{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _post(url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except error.HTTPError as exc:
        detail = ""
        try:
            data = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = str(data.get("error", {}).get("message") or "")[:160]
        except Exception:  # noqa: BLE001
            detail = ""
        mapping = {
            400: "向量接口拒绝了请求（模型名或参数不对）",
            401: "Key 无效或已失效",
            404: "向量接口不存在，确认 base_url 与模型是否支持 /embeddings",
            429: "请求过于频繁或超出配额",
        }
        message = mapping.get(exc.code, f"向量服务返回 HTTP {exc.code}")
        raise HTTPException(502, f"{message}{'：' + detail if detail else ''}") from None
    except (error.URLError, TimeoutError, socket.timeout):
        raise HTTPException(504, "连接向量服务超时，检查 base_url 是否可达") from None

    if len(raw) > MAX_RESPONSE_BYTES:
        raise HTTPException(502, "向量响应过大，请减少单次文本数量")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(502, "向量服务返回的不是合法 JSON") from None


def _load_cached(keys: list[str]) -> dict[str, list[float]]:
    if not keys:
        return {}
    found: dict[str, list[float]] = {}
    with db.tx() as conn:
        for chunk_start in range(0, len(keys), 200):
            chunk = keys[chunk_start : chunk_start + 200]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT key, vector FROM embedding_cache WHERE key IN ({placeholders})", chunk
            ).fetchall()
            for row in rows:
                try:
                    found[row["key"]] = [float(value) for value in json.loads(row["vector"])]
                except (TypeError, ValueError):
                    continue
    return found


def _save_cached(model: str, items: list[tuple[str, list[float]]]) -> None:
    if not items:
        return
    try:
        with db.tx() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO embedding_cache(key,model,vector) VALUES(?,?,?)",
                [(key, model, json.dumps(vector)) for key, vector in items],
            )
    except sqlite3.Error:
        # 缓存失败不影响主流程
        pass


def payload_variants(model: str, texts: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """按兼容性从高到低排列的请求体候选，带可读标签方便排查。"""
    return [
        ("input 数组", {"model": model, "input": texts}),
        ("input.contents[{text}]", {"model": model, "input": {"contents": [{"text": text} for text in texts]}}),
        ("input.contents[str]", {"model": model, "input": {"contents": list(texts)}}),
        (
            "input.contents[{type,text}]",
            {"model": model, "input": {"contents": [{"type": "text", "text": text} for text in texts]}},
        ),
    ]


def _extract_embeddings(data: dict[str, Any], expected: int) -> list[list[float]]:
    """兼容多种响应：data[].embedding、output.embeddings[].embedding。"""
    rows = data.get("data")
    if not isinstance(rows, list):
        output = data.get("output")
        rows = output.get("embeddings") if isinstance(output, dict) else None
    if not isinstance(rows, list) or len(rows) != expected:
        raise HTTPException(502, "向量服务返回结构不符合预期（既不是 data[] 也不是 output.embeddings[]）")
    vectors: list[list[float]] = []
    for item in rows:
        vector = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(vector, list) or not vector:
            raise HTTPException(502, "向量服务返回了空的 embedding")
        vectors.append([float(value) for value in vector])
    return vectors


def _post_batch(url: str, model: str, texts: list[str], api_key: str) -> tuple[list[list[float]], dict[str, Any]]:
    """按批次请求；逐个尝试格式候选，返回第一个成功的。"""
    failures: list[str] = []
    for label, payload in payload_variants(model, texts):
        try:
            data = _post(url, payload, api_key)
        except HTTPException as exc:
            failures.append(f"{label}：{exc.detail}")
            continue
        return _extract_embeddings(data, len(texts)), data.get("usage") or {}
    raise HTTPException(502, "所有向量请求格式都被拒绝 → " + "；".join(failures))


def probe_formats(config: dict[str, Any], text: str = "连接测试") -> list[dict[str, Any]]:
    """逐个尝试请求格式，返回每种格式的结果，用于一次性定位服务商支持的格式。"""
    base_url = (config.get("base_url") or "").strip()
    api_key = (config.get("api_key") or "").strip()
    model = (config.get("model") or "").strip()
    if not base_url or not model or not api_key:
        raise HTTPException(409, "向量模型配置不完整（缺少地址、模型名或 Key）")
    url = endpoint_of(base_url)
    results: list[dict[str, Any]] = []
    for label, payload in payload_variants(model, [text]):
        try:
            data = _post(url, payload, api_key)
        except HTTPException as exc:
            results.append({"format": label, "ok": False, "detail": str(exc.detail)})
            continue
        try:
            vectors = _extract_embeddings(data, 1)
        except HTTPException as exc:
            results.append({"format": label, "ok": False, "detail": f"响应结构不匹配：{exc.detail}"})
            continue
        results.append({"format": label, "ok": True, "dimensions": len(vectors[0]), "detail": ""})
    return results


def embed_texts(
    config: dict[str, Any], texts: list[str], *, use_cache: bool = True
) -> tuple[list[list[float]], dict[str, Any]]:
    """把一批文本转成向量；命中缓存的直接返回，未命中的按批请求。

    返回 (vectors, usage)。vectors 顺序与 texts 严格一致。
    """
    base_url = (config.get("base_url") or "").strip()
    api_key = (config.get("api_key") or "").strip()
    model = (config.get("model") or "").strip()
    if not base_url or not model:
        raise HTTPException(409, "还没有配置向量模型")
    if not api_key:
        raise HTTPException(409, "向量模型没有填写 API Key")
    if len(texts) > MAX_TEXTS:
        raise HTTPException(422, f"单次最多向量化 {MAX_TEXTS} 段文本")

    keys = [cache_key(model, base_url, text) for text in texts]
    cached = _load_cached(keys) if use_cache else {}

    missing: list[int] = [index for index, key in enumerate(keys) if key not in cached]
    usage: dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    url = endpoint_of(base_url)
    for batch_start in range(0, len(missing), BATCH_SIZE):
        batch = missing[batch_start : batch_start + BATCH_SIZE]
        vectors_batch, batch_usage = _post_batch(url, model, [texts[index] for index in batch], api_key)

        fresh: list[tuple[str, list[float]]] = []
        for index, vector in zip(batch, vectors_batch):
            cached[keys[index]] = vector
            fresh.append((keys[index], vector))
        _save_cached(model, fresh)

        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                usage[field] += int(batch_usage.get(field) or 0)
            except (TypeError, ValueError):
                continue

    vectors = [cached[key] for key in keys]
    if any(not vector for vector in vectors):
        raise HTTPException(502, "向量结果不完整，请重试")
    return vectors, usage
