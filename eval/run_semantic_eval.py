"""语义召回评测：规则 vs 规则 + 语义，量化「补回了多少、误报多少」。

为什么单独一套评测：规则评测集（eval/dataset）测的是「能不能抓准」，
而这套测的是「抓不到的同义表述，语义能不能补上，代价是几个误报」。

用法：
    # 1) 纯规则基线（不需要 Key，离线可跑）
    python eval/run_semantic_eval.py

    # 2) 用应用里已配置的向量模型（读取本地库，不用手抄 Key）
    python eval/run_semantic_eval.py --from-db

    # 3) 手动指定（CI 或临时验证）
    python eval/run_semantic_eval.py --base-url https://... --model text-embedding-v3 --api-key sk-xxx

    # 4) 流程自检：用假向量跑通链路，数字无参考意义
    python eval/run_semantic_eval.py --offline-smoke

输出：终端表格 + eval/reports/semantic_report.json + eval/reports/semantic_report.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from backend.detector import analyze_text  # noqa: E402
from backend.semantic import DEFAULT_THRESHOLD, recall  # noqa: E402

DEFAULT_DATASET = HERE / "semantic_cases.jsonl"
REPORT_DIR = HERE / "reports"
TASK = "semantic_recall"


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path.name}:{line_no} 不是合法 JSON：{exc}") from None
        item.setdefault("id", f"line-{line_no}")
        item.setdefault("note", "")
        if "text" not in item or "expect" not in item:
            raise SystemExit(f"{path.name}:{line_no} 缺少 text 或 expect 字段")
        cases.append(item)
    if not cases:
        raise SystemExit(f"{path} 没有任何用例")
    return cases


def smoke_embedder(config: dict[str, Any], texts: list[str]) -> tuple[list[list[float]], dict[str, Any]]:
    """流程自检用的假向量：哈希 bigram + 关键词加权。只验证管道，不产生可信指标。"""
    dims = 128
    keywords = (
        "账期", "付款", "结清", "款项", "支付", "索赔", "赔偿责任", "损害", "不负责",
        "延续", "顺延", "展期", "排他", "仅可与", "代理", "数据", "训练", "可用率",
        "披露", "保密", "成果", "所有权", "知识产权",
    )

    def dim_of(token: str) -> int:
        return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % dims

    vectors: list[list[float]] = []
    for text in texts:
        vector = [0.0] * dims
        for index in range(len(text) - 1):
            vector[dim_of(text[index : index + 2])] += 1.0
        for keyword in keywords:
            if keyword in text:
                vector[dim_of("kw:" + keyword)] += 8.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        vectors.append([value / norm for value in vector])
    return vectors, {"prompt_tokens": len(texts), "completion_tokens": 0, "total_tokens": len(texts)}


def config_from_db() -> dict[str, Any] | None:
    """从本地库读取语义召回配置（不打印 Key）。"""
    from backend import db, recall_settings

    db.init()
    with db.tx() as conn:
        row = conn.execute(
            "SELECT user_id FROM embedding_settings WHERE enabled=1 AND model_id<>'' LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return recall_settings.resolve_config(row["user_id"])


def evaluate(
    cases: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None,
    threshold: float,
    embed_fn: Callable[..., Any] | None,
) -> dict[str, Any]:
    positives = [case for case in cases if case["expect"]]
    negatives = [case for case in cases if not case["expect"]]

    details: list[dict[str, Any]] = []
    rule_hit = 0
    combo_hit = 0
    added_total = 0
    added_correct = 0
    negative_fp = 0

    for case in cases:
        text = str(case["text"])
        expect = case["expect"]
        doc_id = f"eval-{case['id']}"
        rule_clauses = analyze_text(doc_id, text)
        rule_titles = [clause["title"] for clause in rule_clauses]

        extra: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        if config:
            extra, usage, _stats = recall(
                doc_id,
                text,
                [(clause["start_offset"], clause["end_offset"]) for clause in rule_clauses],
                config=config,
                threshold=threshold,
                embed_fn=embed_fn,
            )

        extra_titles = [clause["title"] for clause in extra]
        added_total += len(extra_titles)

        record: dict[str, Any] = {
            "id": case["id"],
            "expect": expect,
            "rule_titles": rule_titles,
            "semantic_titles": extra_titles,
            "note": case["note"],
        }

        if expect:
            hit_rule = expect in rule_titles
            hit_combo = hit_rule or expect in extra_titles
            rule_hit += 1 if hit_rule else 0
            combo_hit += 1 if hit_combo else 0
            if expect in extra_titles:
                added_correct += 1
            record["rule_hit"] = hit_rule
            record["combo_hit"] = hit_combo
        else:
            false_positive = bool(rule_titles) or bool(extra_titles)
            negative_fp += 1 if false_positive else 0
            record["false_positive"] = false_positive

        if usage.get("total_tokens"):
            record["tokens"] = usage.get("total_tokens")
        details.append(record)

    summary = {
        "positives": len(positives),
        "negatives": len(negatives),
        "rule_recall": round(rule_hit / len(positives), 4) if positives else 0.0,
        "combo_recall": round(combo_hit / len(positives), 4) if positives else 0.0,
        "semantic_added": added_total,
        "semantic_added_correct": added_correct,
        "semantic_precision": round(added_correct / added_total, 4) if added_total else None,
        "negative_false_positive": negative_fp,
        "threshold": round(threshold, 3),
        "config": bool(config),
    }
    return {"task": TASK, "summary": summary, "cases": details}


def render_markdown(report: dict[str, Any], dataset: str) -> str:
    summary = report["summary"]
    lines = [
        "# 语义召回评测报告",
        "",
        f"- 数据集：`{dataset}`（正例 {summary['positives']} / 负例 {summary['negatives']}）",
        f"- 阈值：{summary['threshold']}",
        f"- 是否接入向量模型：{'是' if summary['config'] else '否（仅规则基线）'}",
        "",
        "| 方案 | 正例命中 | 召回率 | 负例误报 |",
        "| --- | --- | --- | --- |",
        f"| 纯规则 | {round(summary['rule_recall'] * summary['positives'])}"
        f" / {summary['positives']} | {summary['rule_recall']:.1%} |"
        f" {summary['negative_false_positive']} / {summary['negatives']} |",
    ]
    combo_count = round(summary["combo_recall"] * summary["positives"])
    precision = summary["semantic_precision"]
    precision_text = f"{precision:.1%}" if isinstance(precision, float) else "—"
    lines.append(
        f"| 规则 + 语义 | {combo_count} / {summary['positives']} | {summary['combo_recall']:.1%}"
        f" | {summary['negative_false_positive']} / {summary['negatives']}"
        f"（语义补 {summary['semantic_added']} 条，准确 {precision_text}） |"
    )

    missed = [case for case in report["cases"] if case["expect"] and not case.get("combo_hit")]
    if missed:
        lines += ["", "## 仍未命中", ""]
        lines += [
            f"- `{case['id']}` 期望「{case['expect']}」，规则 {case['rule_titles'] or '无'}，"
            f"语义 {case['semantic_titles'] or '无'}（{case['note']}）"
            for case in missed
        ]

    false_positives = [case for case in report["cases"] if case.get("false_positive")]
    if false_positives:
        lines += ["", "## 负例误报", ""]
        lines += [
            f"- `{case['id']}` 规则 {case['rule_titles'] or '无'}，语义 {case['semantic_titles'] or '无'}"
            for case in false_positives
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="语义召回评测")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--from-db", action="store_true", help="读取应用里已配置的向量模型")
    parser.add_argument("--base-url", default=os.environ.get("EMBED_BASE_URL", ""))
    parser.add_argument("--model", default=os.environ.get("EMBED_MODEL", ""))
    parser.add_argument("--api-key", default=os.environ.get("EMBED_API_KEY", ""))
    parser.add_argument("--offline-smoke", action="store_true", help="用假向量跑通流程，指标无意义")
    parser.add_argument("--no-write", action="store_true", help="只打印，不写报告文件")
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.dataset))

    config: dict[str, Any] | None = None
    embed_fn: Callable[..., Any] | None = None
    label = "纯规则基线"
    if args.offline_smoke:
        config = {"base_url": "https://offline.invalid", "model": "smoke", "api_key": "smoke"}
        embed_fn = smoke_embedder
        label = "离线自检（假向量，指标无意义）"
    elif args.from_db:
        config = config_from_db()
        if not config:
            print("本地库里没有启用的语义召回配置（embedding_settings.enabled=1 且选了模型）")
            print("先在应用里开启语义召回并点一次审阅，或改用 --base-url/--model/--api-key")
            return 2
        label = "读取本地库配置"
    elif args.base_url and args.model and args.api_key:
        config = {"base_url": args.base_url, "model": args.model, "api_key": args.api_key}
        label = "手工指定模型"
    elif args.base_url or args.model or args.api_key:
        print("--base-url / --model / --api-key 需要同时提供")
        return 2

    report = evaluate(cases, config=config, threshold=args.threshold, embed_fn=embed_fn)
    report["label"] = label
    report["dataset"] = Path(args.dataset).name

    summary = report["summary"]
    print(f"\n数据源：{label}")
    print(f"正例 {summary['positives']} / 负例 {summary['negatives']}，阈值 {summary['threshold']}")
    print(f"纯规则召回率      {summary['rule_recall']:.1%}")
    if config:
        precision = summary["semantic_precision"]
        print(f"规则 + 语义召回率 {summary['combo_recall']:.1%}")
        print(
            f"语义补充 {summary['semantic_added']} 条，其中正确 {summary['semantic_added_correct']} 条"
            + (f"（准确率 {precision:.1%}）" if isinstance(precision, float) else "")
        )
        print(f"负例误报         {summary['negative_false_positive']} / {summary['negatives']}")

    missed = [case for case in report["cases"] if case["expect"] and not case.get("combo_hit")]
    if missed:
        print("\n仍未命中：")
        for case in missed:
            print(f"  - {case['id']} 期望「{case['expect']}」：{case['note']}")

    if not args.no_write:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "semantic_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (REPORT_DIR / "semantic_report.md").write_text(
            render_markdown(report, report["dataset"]), encoding="utf-8"
        )
        print(f"\n报告已写入 {REPORT_DIR / 'semantic_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
