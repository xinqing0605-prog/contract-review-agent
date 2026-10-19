"""条款检测评测。

用法：
    python eval/run_eval.py
    python eval/run_eval.py --dataset eval/dataset/cases.jsonl --iou 0.5

输出：终端表格 + eval/reports/report.json + eval/reports/report.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from backend.detector import analyze_text  # noqa: E402
from eval.metrics import (  # noqa: E402
    Span,
    contains,
    greedy_match,
    grounding_ok,
    iou,
    pad,
    prf,
    resolve_quote,
)


def load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw or raw.startswith("//"):
            continue
        try:
            cases.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path.name}:{lineno} JSON 解析失败：{exc}") from exc
    if not cases:
        raise SystemExit(f"{path} 里没有用例")
    return cases


def evaluate_case(case: dict, iou_threshold: float) -> dict:
    text = case["text"]
    gold_items = case.get("gold", [])
    golds: list[tuple[str, Span]] = []
    for item in gold_items:
        span = resolve_quote(text, item["quote"])
        golds.append((item["type"], span))

    preds_raw = analyze_text(case["id"], text)
    preds: list[tuple[str, Span]] = [
        (c["title"], Span(c["start_offset"], c["end_offset"])) for c in preds_raw
    ]

    matched = greedy_match(golds, preds, iou_threshold)
    matched_g = {gi for gi, _, _ in matched}
    matched_p = {pi for _, pi, _ in matched}

    tp = len(matched)
    fn = len(golds) - tp
    fp = len(preds) - tp

    risk_hits = 0
    for gi, pi, _ in matched:
        if gold_items[gi].get("risk") == preds_raw[pi]["risk"]:
            risk_hits += 1

    contained = sum(
        1 for gi, pi, _ in matched if contains(preds[pi][1], golds[gi][1])
    )

    grounding = sum(
        1
        for clause in preds_raw
        if grounding_ok(text, clause["original"], Span(clause["start_offset"], clause["end_offset"]))
    )

    return {
        "id": case["id"],
        "name": case.get("name", ""),
        "gold": len(golds),
        "pred": len(preds),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "risk_accuracy": risk_hits / tp if tp else 0.0,
        "containment": contained / tp if tp else 0.0,
        "grounding": grounding / len(preds_raw) if preds_raw else 1.0,
        "mean_iou": sum(score for _, _, score in matched) / tp if tp else 0.0,
        "missed": [golds[gi][0] for gi in range(len(golds)) if gi not in matched_g],
        "spurious": [preds[pi][0] for pi in range(len(preds)) if pi not in matched_p],
    }


def render(results: list[dict], iou_threshold: float) -> str:
    head = ["#", "case", "gold", "pred", "TP", "FP", "FN", "risk", "IoU", "接地"]
    widths = [3, 26, 5, 5, 4, 4, 4, 6, 6, 5]
    lines = ["  ".join(pad(h, w) for h, w in zip(head, widths))]
    lines.append("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for index, row in enumerate(results, 1):
        values = [
            index,
            row["name"][:24],
            row["gold"],
            row["pred"],
            row["tp"],
            row["fp"],
            row["fn"],
            f"{row['risk_accuracy']:.0%}",
            f"{row['mean_iou']:.2f}",
            f"{row['grounding']:.0%}",
        ]
        lines.append("  ".join(pad(v, w) for v, w in zip(values, widths)))

    tp = sum(r["tp"] for r in results)
    fp = sum(r["fp"] for r in results)
    fn = sum(r["fn"] for r in results)
    scores = prf(tp, fp, fn)
    lines.append("")
    lines.append(
        f"合计 TP={tp} FP={fp} FN={fn}  "
        f"P={scores['precision']:.3f}  R={scores['recall']:.3f}  F1={scores['f1']:.3f}"
    )
    lines.append(f"定位阈值 IoU >= {iou_threshold:.2f}；用例数 {len(results)}")

    misses = [(r["name"], r["missed"]) for r in results if r["missed"]]
    if misses:
        lines.append("")
        lines.append("漏检：")
        for name, items in misses:
            lines.append(f"  - {name}: {', '.join(items)}")
    spurious = [(r["name"], r["spurious"]) for r in results if r["spurious"]]
    if spurious:
        lines.append("")
        lines.append("误报：")
        for name, items in spurious:
            lines.append(f"  - {name}: {', '.join(items)}")
    return "\n".join(lines)


def markdown(results: list[dict], iou_threshold: float) -> str:
    tp = sum(r["tp"] for r in results)
    fp = sum(r["fp"] for r in results)
    fn = sum(r["fn"] for r in results)
    scores = prf(tp, fp, fn)
    risk = sum(r["risk_accuracy"] * r["tp"] for r in results) / tp if tp else 0.0
    grounding = sum(r["grounding"] * r["pred"] for r in results) / max(
        1, sum(r["pred"] for r in results)
    )
    out = [
        "# 条款检测评测报告",
        "",
        f"- 用例数：{len(results)}",
        f"- 定位阈值：IoU >= {iou_threshold:.2f}",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| Precision | {scores['precision']:.3f} |",
        f"| Recall | {scores['recall']:.3f} |",
        f"| F1 | {scores['f1']:.3f} |",
        f"| 风险分级准确率（匹配项内） | {risk:.1%} |",
        f"| 原文引用接地率 | {grounding:.1%} |",
        "",
        "| 用例 | 标注 | 检出 | TP | FP | FN | 平均 IoU |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in results:
        out.append(
            f"| {row['name']} | {row['gold']} | {row['pred']} | {row['tp']} | "
            f"{row['fp']} | {row['fn']} | {row['mean_iou']:.2f} |"
        )
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="条款检测评测")
    parser.add_argument("--dataset", default=str(HERE / "dataset" / "cases.jsonl"))
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--json", default=str(HERE / "reports" / "report.json"))
    parser.add_argument("--md", default=str(HERE / "reports" / "report.md"))
    args = parser.parse_args()

    cases = load_cases(Path(args.dataset))
    results = [evaluate_case(case, args.iou) for case in cases]

    print(render(results, args.iou))

    out_json = Path(args.json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(
            {
                "iou_threshold": args.iou,
                "aggregate": prf(
                    sum(r["tp"] for r in results),
                    sum(r["fp"] for r in results),
                    sum(r["fn"] for r in results),
                ),
                "cases": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    Path(args.md).write_text(markdown(results, args.iou), encoding="utf-8")
    print(f"\n已写入 {out_json} 和 {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
