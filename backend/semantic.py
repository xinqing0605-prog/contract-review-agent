"""语义召回：把合同逐句向量化，与样本库比对，补上规则漏检的同义表述。

定位：**补充通道，不替代规则**。
- 规则命中 → 保留规则的类别、风险与原文切片（可复现、可评测）
- 规则没命中、但某句与样本库的相似度超过阈值 → 补一条候选，reason 里写明「语义相似」

代价：需要一次向量化调用（按句数计费），因此默认关闭，由用户在设置里显式开启。
"""
from __future__ import annotations

import math
from typing import Any, Callable

from .detector import EXCERPT_CHARS, MAX_CLAUSE_CHARS, SENTENCE_END
from .semantic_patterns import (
    RECOMMEND_OF_TITLE,
    REASON_OF_TITLE,
    RISK_OF_TITLE,
    SEMANTIC_PATTERNS,
)

DEFAULT_THRESHOLD = 0.82
MIN_THRESHOLD = 0.60
MAX_THRESHOLD = 0.95
MIN_SENTENCE_CHARS = 8
# 与规则条款重合超过这个比例就跳过，避免重复标注同一句话
OVERLAP_SKIP_RATIO = 0.5


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    """按句切开，返回 (start, end, body)；偏移量相对全文。"""
    spans: list[tuple[int, int, str]] = []
    left = 0
    for index, char in enumerate(text):
        if char in SENTENCE_END:
            spans.append((left, index + 1))
            left = index + 1
    if left < len(text):
        spans.append((left, len(text)))

    cleaned: list[tuple[int, int, str]] = []
    for start, end in spans:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end - start < MIN_SENTENCE_CHARS:
            continue
        if end - start > MAX_CLAUSE_CHARS:
            end = start + MAX_CLAUSE_CHARS
        cleaned.append((start, end, text[start:end]))
    return cleaned


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)


def pattern_items() -> list[tuple[str, str]]:
    """展开样本库：[(类别, 句子), ...]。"""
    items: list[tuple[str, str]] = []
    for title, sentences in SEMANTIC_PATTERNS.items():
        for sentence in sentences:
            items.append((title, sentence))
    return items


def _overlaps(span: tuple[int, int], existing: list[tuple[int, int]]) -> bool:
    start, end = span
    length = max(1, end - start)
    for other_start, other_end in existing:
        overlap = min(end, other_end) - max(start, other_start)
        if overlap > 0 and overlap / length >= OVERLAP_SKIP_RATIO:
            return True
    return False


def recall(
    document_id: str,
    text: str,
    existing_spans: list[tuple[int, int]],
    *,
    config: dict[str, Any],
    threshold: float = DEFAULT_THRESHOLD,
    embed_fn: Callable[[dict[str, Any], list[str]], tuple[list[list[float]], dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """返回 (候选条款, 用量, 统计)。embed_fn 可注入，便于离线测试。"""
    threshold = min(MAX_THRESHOLD, max(MIN_THRESHOLD, float(threshold or DEFAULT_THRESHOLD)))
    if embed_fn is None:
        from .embeddings import embed_texts as embed_fn  # 延迟导入，测试可替换

    sentences = [item for item in split_sentences(text) if not _overlaps((item[0], item[1]), existing_spans)]
    stats = {
        "sentences": len(sentences),
        "threshold": round(threshold, 3),
        "candidates": 0,
        "skipped_by_overlap": len(split_sentences(text)) - len(sentences),
    }
    if not sentences:
        return [], {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, stats

    patterns = pattern_items()
    sentence_vectors, usage_a = embed_fn(config, [item[2] for item in sentences])
    pattern_vectors, usage_b = embed_fn(config, [text for _, text in patterns])
    usage = {
        field: int(usage_a.get(field, 0)) + int(usage_b.get(field, 0))
        for field in ("prompt_tokens", "completion_tokens", "total_tokens")
    }

    clauses: list[dict[str, Any]] = []
    for (start, end, body), vector in zip(sentences, sentence_vectors):
        best_title = ""
        best_score = 0.0
        best_pattern = ""
        for (title, pattern_text), pattern_vector in zip(patterns, pattern_vectors):
            score = cosine(vector, pattern_vector)
            if score > best_score:
                best_score, best_title, best_pattern = score, title, pattern_text
        if best_score < threshold or not best_title:
            continue

        excerpt = body if len(body) <= EXCERPT_CHARS else body[:EXCERPT_CHARS] + "…"
        clauses.append(
            {
                "id": "",  # 由调用方统一编号
                "document_id": document_id,
                "title": best_title,
                "risk": RISK_OF_TITLE.get(best_title, "medium"),
                "excerpt": excerpt,
                "original": body,
                "reason": f"{REASON_OF_TITLE.get(best_title, '')}（语义相似：{best_pattern[:24]}…）",
                "recommend": RECOMMEND_OF_TITLE.get(best_title, ""),
                "start_offset": start,
                "end_offset": end,
                "accepted": 0,
                "match_score": round(best_score, 3),
                "source": "semantic",
            }
        )

    stats["candidates"] = len(clauses)
    return clauses, usage, stats
