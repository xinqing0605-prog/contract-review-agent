"""语义召回评测集与评测脚本的自检。

这组测试的作用：防止评测集腐化。
如果哪天规则被加强、把某个正例抓到了，或者数据集格式改坏，
这里会先失败，提醒更新预期，而不是让评测报告静默失真。
"""
import os
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cg-sem-eval-"))
os.environ.setdefault("CLAUSEGUARD_DB", str(TMP / "test.sqlite3"))
os.environ.setdefault("CLAUSEGUARD_DATA", str(TMP))
os.environ.setdefault("CLAUSEGUARD_ALLOW_PRIVATE_MODEL", "0")

from backend.detector import PATTERNS  # noqa: E402
from eval.run_semantic_eval import (  # noqa: E402
    DEFAULT_DATASET,
    evaluate,
    load_cases,
    smoke_embedder,
)

TITLES = {pattern.title for pattern in PATTERNS}


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases(DEFAULT_DATASET)

    def test_case_count_and_ids(self):
        self.assertGreaterEqual(len(self.cases), 15)
        ids = [case["id"] for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)), "用例 id 不能重复")

    def test_expected_titles_are_detector_categories(self):
        for case in self.cases:
            if case["expect"]:
                self.assertIn(case["expect"], TITLES, f"{case['id']} 的期望类别不存在")

    def test_has_both_positives_and_negatives(self):
        positives = [case for case in self.cases if case["expect"]]
        negatives = [case for case in self.cases if not case["expect"]]
        self.assertGreaterEqual(len(positives), 10)
        self.assertGreaterEqual(len(negatives), 4)

    def test_every_case_has_note(self):
        for case in self.cases:
            self.assertTrue(case["note"].strip(), f"{case['id']} 缺少 note，后续维护会失去依据")


class BaselineTests(unittest.TestCase):
    """纯规则基线：正例应该基本抓不到，负例不该误报。"""

    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases(DEFAULT_DATASET)
        cls.report = evaluate(cls.cases, config=None, threshold=0.82, embed_fn=None)

    def test_rules_miss_most_positives(self):
        summary = self.report["summary"]
        # 数据集的意义就是「规则抓不到」：若命中超过 2 条，说明该换新用例了
        hits = round(summary["rule_recall"] * summary["positives"])
        self.assertLessEqual(hits, 2, "规则已经能抓到这些同义句，数据集需要更新")

    def test_rules_produce_no_false_positive_on_negatives(self):
        summary = self.report["summary"]
        self.assertEqual(summary["negative_false_positive"], 0)

    def test_report_contains_every_case(self):
        self.assertEqual(len(self.report["cases"]), len(self.cases))


class SmokeTests(unittest.TestCase):
    """假向量跑通链路：只验证脚本能算出数，不对指标做断言。"""

    def test_smoke_run_produces_metrics(self):
        cases = load_cases(DEFAULT_DATASET)
        report = evaluate(
            cases,
            config={"base_url": "https://offline.invalid", "model": "smoke", "api_key": "smoke"},
            threshold=0.82,
            embed_fn=smoke_embedder,
        )
        summary = report["summary"]
        self.assertGreater(summary["semantic_added"], 0)
        self.assertGreaterEqual(summary["combo_recall"], summary["rule_recall"])
        self.assertIsNotNone(summary["semantic_precision"])


if __name__ == "__main__":
    unittest.main()
