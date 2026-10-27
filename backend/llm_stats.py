"""模型调用记录与用量统计。

只做两件事：
1. 把每次模型调用（成功或失败）写进 llm_calls 表；
2. 按用户聚合最近 N 天的调用次数、token、耗时与失败情况。

刻意保持"旁路"：记录失败只打日志，绝不抛错，避免统计影响审阅主流程。
"""
from __future__ import annotations

import logging
import math
from typing import Any

from . import db

logger = logging.getLogger(__name__)

PURPOSE_LABEL = {
    "review": "合同审阅",
    "connection_check": "连接检测",
    "embedding": "语义召回",
}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def record(
    *,
    user_id: str,
    purpose: str,
    model: str = "",
    base_url: str = "",
    usage: dict[str, Any] | None = None,
    duration_ms: float = 0,
    ok: bool = True,
    error: str = "",
    document_id: str | None = None,
) -> None:
    """写一条调用记录；任何异常都吞掉。"""
    if not user_id:
        return
    usage = usage or {}
    try:
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO llm_calls(user_id,document_id,purpose,model,base_url,"
                "prompt_tokens,completion_tokens,total_tokens,duration_ms,ok,error) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    user_id,
                    document_id,
                    purpose,
                    (model or "")[:120],
                    (base_url or "")[:300],
                    _as_int(usage.get("prompt_tokens")),
                    _as_int(usage.get("completion_tokens")),
                    _as_int(usage.get("total_tokens")),
                    round(float(duration_ms or 0), 2),
                    1 if ok else 0,
                    (error or "")[:300],
                ),
            )
    except Exception:  # noqa: BLE001 - 统计失败不能影响主流程
        logger.warning("记录模型调用失败", exc_info=True)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
    return round(ordered[index], 1)


def summary(user_id: str, days: int = 7, recent_limit: int = 20) -> dict[str, Any]:
    """返回最近 N 天的用量汇总，结构直接给前端用。"""
    if not user_id:
        return {"days": 0, "totals": {}, "by_day": [], "by_model": [], "recent": []}
    days = max(1, min(int(days or 7), 90))
    with db.tx() as conn:
        since = conn.execute("SELECT datetime('now', ?)", (f"-{days} day",)).fetchone()[0]
        rows = conn.execute(
            "SELECT id,document_id,purpose,model,total_tokens,prompt_tokens,completion_tokens,"
            "duration_ms,ok,error,created_at FROM llm_calls "
            "WHERE user_id=? AND created_at >= ? ORDER BY created_at DESC",
            (user_id, since),
        ).fetchall()

    calls = len(rows)
    failed = sum(1 for row in rows if not row["ok"])
    durations = [float(row["duration_ms"] or 0) for row in rows if row["ok"]]
    totals = {
        "calls": calls,
        "ok": calls - failed,
        "failed": failed,
        "prompt_tokens": sum(int(row["prompt_tokens"] or 0) for row in rows),
        "completion_tokens": sum(int(row["completion_tokens"] or 0) for row in rows),
        "total_tokens": sum(int(row["total_tokens"] or 0) for row in rows),
        "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "p95_duration_ms": _p95(durations),
    }

    by_day: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = str(row["created_at"] or "")[:10]
        bucket = by_day.setdefault(day, {"date": day, "calls": 0, "failed": 0, "total_tokens": 0})
        bucket["calls"] += 1
        bucket["total_tokens"] += int(row["total_tokens"] or 0)
        if not row["ok"]:
            bucket["failed"] += 1

    by_model: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row["model"] or "未记录")
        bucket = by_model.setdefault(
            name, {"model": name, "calls": 0, "failed": 0, "total_tokens": 0, "_durations": []}
        )
        bucket["calls"] += 1
        bucket["total_tokens"] += int(row["total_tokens"] or 0)
        if not row["ok"]:
            bucket["failed"] += 1
        else:
            bucket["_durations"].append(float(row["duration_ms"] or 0))
    models = []
    for bucket in by_model.values():
        values = bucket.pop("_durations")
        bucket["avg_duration_ms"] = round(sum(values) / len(values), 1) if values else 0.0
        models.append(bucket)
    models.sort(key=lambda item: (-item["calls"], item["model"]))

    recent = [
        {
            "id": row["id"],
            "document_id": row["document_id"],
            "purpose": row["purpose"],
            "purpose_label": PURPOSE_LABEL.get(str(row["purpose"]), str(row["purpose"])),
            "model": row["model"],
            "total_tokens": int(row["total_tokens"] or 0),
            "duration_ms": round(float(row["duration_ms"] or 0), 1),
            "ok": bool(row["ok"]),
            "error": row["error"],
            "created_at": row["created_at"],
        }
        for row in rows[: max(1, min(int(recent_limit or 20), 100))]
    ]

    return {
        "days": days,
        "since": since,
        "totals": totals,
        "by_day": sorted(by_day.values(), key=lambda item: item["date"]),
        "by_model": models,
        "recent": recent,
    }
