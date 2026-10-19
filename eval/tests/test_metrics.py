import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.metrics import Span, contains, greedy_match, iou, prf, resolve_quote  # noqa: E402


class SpanMathTests(unittest.TestCase):
    def test_iou_identical(self):
        self.assertAlmostEqual(iou(Span(0, 10), Span(0, 10)), 1.0)

    def test_iou_disjoint(self):
        self.assertEqual(iou(Span(0, 10), Span(20, 30)), 0.0)

    def test_iou_half_overlap(self):
        self.assertAlmostEqual(iou(Span(0, 10), Span(5, 15)), 1 / 3)

    def test_contains(self):
        self.assertTrue(contains(Span(0, 20), Span(5, 10)))
        self.assertFalse(contains(Span(0, 20), Span(15, 25)))


class MatchingTests(unittest.TestCase):
    def test_one_to_one_greedy(self):
        golds = [("A", Span(0, 10)), ("A", Span(100, 110))]
        preds = [("A", Span(0, 10))]
        matched = greedy_match(golds, preds, 0.5)
        self.assertEqual(len(matched), 1)

    def test_type_must_match(self):
        golds = [("A", Span(0, 10))]
        preds = [("B", Span(0, 10))]
        self.assertEqual(greedy_match(golds, preds, 0.5), [])


class QuoteTests(unittest.TestCase):
    def test_resolve_existing_quote(self):
        span = resolve_quote("甲方应付款。乙方应交付。", "乙方应交付。")
        self.assertEqual(span, Span(6, 12))

    def test_resolve_rejects_missing(self):
        with self.assertRaises(ValueError):
            resolve_quote("甲方应付款。", "乙方应交付。")

    def test_resolve_rejects_ambiguous(self):
        with self.assertRaises(ValueError):
            resolve_quote("付款。付款。", "付款。")


class PrfTests(unittest.TestCase):
    def test_all_correct(self):
        self.assertEqual(prf(10, 0, 0)["f1"], 1.0)

    def test_zero_everything(self):
        self.assertEqual(prf(0, 0, 0)["f1"], 0.0)


if __name__ == "__main__":
    unittest.main()
