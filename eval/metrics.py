"""评测指标。纯函数，不依赖后端和网络，可单独单测。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Span:
    start: int
    end: int


def iou(a: Span, b: Span) -> float:
    inter = max(0, min(a.end, b.end) - max(a.start, b.start))
    if inter <= 0:
        return 0.0
    union = (a.end - a.start) + (b.end - b.start) - inter
    return inter / union if union > 0 else 0.0


def contains(outer: Span, inner: Span) -> bool:
    return outer.start <= inner.start and inner.end <= outer.end


def resolve_quote(text: str, quote: str) -> Span:
    """用原句反查偏移。必须唯一，否则标注不可信。"""
    first = text.find(quote)
    if first < 0:
        raise ValueError(f"quote 不在正文中：{quote[:40]}…")
    if text.find(quote, first + 1) >= 0:
        raise ValueError(f"quote 不唯一，请加长到能唯一定位：{quote[:40]}…")
    return Span(first, first + len(quote))


def greedy_match(
    golds: Sequence[tuple[str, Span]],
    preds: Sequence[tuple[str, Span]],
    iou_threshold: float,
) -> list[tuple[int, int, float]]:
    """一对一匹配，同类型才允许配对，按 IoU 从高到低贪心。"""
    candidates: list[tuple[float, int, int]] = []
    for gi, (gtype, gspan) in enumerate(golds):
        for pi, (ptype, pspan) in enumerate(preds):
            if gtype != ptype:
                continue
            score = iou(gspan, pspan)
            if score >= iou_threshold:
                candidates.append((score, gi, pi))
    candidates.sort(reverse=True)
    used_g: set[int] = set()
    used_p: set[int] = set()
    matched: list[tuple[int, int, float]] = []
    for score, gi, pi in candidates:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        matched.append((gi, pi, score))
    return matched


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def grounding_ok(text: str, original: str, span: Span) -> bool:
    """引用接地：报告的原文必须是正文的精确切片，不允许模型自己写。"""
    if not (0 <= span.start < span.end <= len(text)):
        return False
    return text[span.start : span.end] == original


def display_width(value: str) -> int:
    import unicodedata

    width = 0
    for ch in str(value):
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def pad(value: object, width: int) -> str:
    text = str(value)
    return text + " " * max(0, width - display_width(text))
