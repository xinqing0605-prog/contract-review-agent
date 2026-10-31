"""相似历史案例：给当前条款找「以前类似条款是怎么处置的」。

价值：合同审阅最大的重复劳动是「这条以前怎么定的」。把本人历史处置结论（采纳 / 驳回 / 批注）
按语义相似度召回，能直接复用判断，而不是每份合同从头想。

成本控制（很重要）：
- 候选池只取同一用户、**同一类别**、**已处置**（非 pending）的最近 N 条，不做全库比较
- 向量走 embeddings 的缓存，同一句话只算一次
- 没配置向量模型时返回空列表 + 原因，不报错
"""
from __future__ import annotations

from typing import Any, Callable

from .semantic import cosine

CANDIDATE_LIMIT = 50
DEFAULT_SIMILAR_LIMIT = 3
MIN_SCORE = 0.55  # 低于这个相似度不算「相似案例」

DISPOSITION_LABEL = {
    "approved": "已采纳",
    "rejected": "已驳回",
    "executed": "已执行",
    "pending": "未处置",
}


def _decision_of(row: Any) -> str:
    status = (row["status"] or "pending").strip()
    if status in ("approved", "executed"):
        return status
    if status == "rejected":
        return "rejected"
    if row["accepted"]:
        return "approved"
    return "pending"


def candidates(user_id: str, title: str, exclude_clause_id: str) -> list[Any]:
    """同一用户、同类别的已处置条款，取最近的若干条。"""
    from . import db

    with db.tx() as conn:
        return conn.execute(
            "SELECT c.id, c.title, c.risk, c.original, c.status, c.accepted, c.comment, "
            "c.reject_reason, c.updated_at, d.name AS document_name "
            "FROM clauses c JOIN documents d ON d.id = c.document_id "
            "WHERE d.user_id=? AND COALESCE(d.deleted,0)=0 AND c.title=? AND c.id<>? "
            "AND (COALESCE(c.status,'pending')<>'pending' OR c.accepted=1 "
            "     OR COALESCE(c.comment,'')<>'' OR COALESCE(c.reject_reason,'')<>'') "
            "ORDER BY COALESCE(c.updated_at, c.id) DESC LIMIT ?",
            (user_id, title, exclude_clause_id, CANDIDATE_LIMIT),
        ).fetchall()


def find_similar(
    user_id: str,
    clause: dict[str, Any],
    *,
    config: dict[str, Any] | None,
    limit: int = DEFAULT_SIMILAR_LIMIT,
    embed_fn: Callable[[dict[str, Any], list[str]], tuple[list[list[float]], dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """返回 (相似案例列表, 提示原因)。config 为空时返回空列表 + 原因。"""
    if not config:
        return [], "未配置向量模型，无法检索历史案例"
    body = (clause.get("original") or "").strip()
    if not body:
        return [], "条款没有原文，无法比较"

    rows = candidates(user_id, clause.get("title") or "", clause.get("id") or "")
    if not rows:
        return [], "还没有同类条款的历史处置记录"

    if embed_fn is None:
        from .embeddings import embed_texts as embed_fn

    texts = [body] + [(row["original"] or "").strip() for row in rows]
    vectors, _usage = embed_fn(config, texts)
    target = vectors[0]

    scored: list[tuple[float, Any]] = []
    for row, vector in zip(rows, vectors[1:]):
        score = cosine(target, vector)
        if score >= MIN_SCORE:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)

    results: list[dict[str, Any]] = []
    for score, row in scored[: max(1, limit)]:
        decision = _decision_of(row)
        results.append(
            {
                "clause_id": row["id"],
                "document_name": row["document_name"],
                "title": row["title"],
                "risk": row["risk"],
                "decision": decision,
                "decision_label": DISPOSITION_LABEL.get(decision, decision),
                "comment": row["comment"] or "",
                "reject_reason": row["reject_reason"] or "",
                "excerpt": (row["original"] or "")[:120],
                "score": round(score, 3),
                "updated_at": row["updated_at"],
            }
        )
    if not results:
        return [], "历史案例里没有足够相似的条款"
    return results, ""
