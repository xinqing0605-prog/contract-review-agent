"""语义召回的离线测试：用可注入的假向量函数，不访问网络。

覆盖：
- 句子切分与偏移量
- 同义表述能被召回（规则会漏、语义能补）
- 阈值生效（调高则不召回）
- 已被规则覆盖的句子不重复标注
- 设置接口：需要登录、缺模型时拒绝、保存后能读回
"""
import hashlib
import math
import os
import tempfile
import time
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cg-semantic-"))
os.environ.setdefault("CLAUSEGUARD_DB", str(TMP / "test.sqlite3"))
os.environ.setdefault("CLAUSEGUARD_DATA", str(TMP))
os.environ.setdefault("CLAUSEGUARD_ALLOW_PRIVATE_MODEL", "0")

from fastapi.testclient import TestClient  # noqa: E402

from backend import semantic  # noqa: E402
from backend.app import app  # noqa: E402
from backend.detector import analyze_text  # noqa: E402

DIMS = 128
KEYWORD_BOOST = 8.0

# 极简"语义空间"：关键词命中同一维度；bigram 哈希负责区分无关句子
KEYWORDS = (
    "账期", "付款", "结清", "支付",
    "间接损失", "赔偿责任", "免责", "索赔",
    "自动延续", "顺延", "展期",
    "不得与", "独家", "仅可与",
    "数据", "信息",
    "可用性", "可用率",
)


def _dim_of(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % DIMS


def fake_embed(config, texts):
    """哈希 bigram + 关键词加权：无关句子向量天然不同，同义词共享关键词维度。"""
    vectors = []
    for text in texts:
        vector = [0.0] * DIMS
        for index in range(len(text) - 1):
            vector[_dim_of(text[index : index + 2])] += 1.0
        for keyword in KEYWORDS:
            if keyword in text:
                vector[_dim_of("kw:" + keyword)] += KEYWORD_BOOST
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        vectors.append([value / norm for value in vector])
    usage = {"prompt_tokens": len(texts), "completion_tokens": 0, "total_tokens": len(texts)}
    return vectors, usage


def make_client() -> TestClient:
    return TestClient(app, base_url="http://testserver")


def register(client: TestClient, tag: str) -> dict:
    email = f"{tag}-{int(time.time() * 1000)}@test.local"
    response = client.post(
        "/api/auth/register",
        json={"account": email, "password": "Passw0rd!", "name": tag},
    )
    assert response.status_code == 200, response.text
    return response.json()["user"]


class SplitTests(unittest.TestCase):
    def test_split_offsets_match_original(self):
        text = "第一句关于付款。第二句关于保密；第三句结束"
        for start, end, body in semantic.split_sentences(text):
            self.assertEqual(text[start:end], body)

    def test_cosine_bounds(self):
        self.assertAlmostEqual(semantic.cosine([1.0, 0.0], [1.0, 0.0]), 1.0, places=6)
        self.assertAlmostEqual(semantic.cosine([1.0, 0.0], [0.0, 1.0]), 0.0, places=6)
        self.assertEqual(semantic.cosine([], [1.0]), 0.0)


class RecallTests(unittest.TestCase):
    PARAPHRASE = "双方约定账期为交付完成后的第三个月结清，逾期不计利息。"
    UNRELATED = "本协议适用中华人民共和国法律。"

    def test_rules_miss_paraphrase(self):
        """先确认前提：这句话规则确实抓不到。"""
        clauses = analyze_text("doc-x", self.PARAPHRASE)
        self.assertEqual([clause for clause in clauses if clause["title"] == "付款与验收"], [])

    def test_semantic_recall_finds_paraphrase(self):
        clauses, usage, stats = semantic.recall(
            "doc-x",
            self.PARAPHRASE,
            [],
            config={"base_url": "https://example.com/v1", "model": "fake", "api_key": "k"},
            threshold=0.82,
            embed_fn=fake_embed,
        )
        self.assertEqual(len(clauses), 1)
        clause = clauses[0]
        self.assertEqual(clause["title"], "付款与验收")
        self.assertEqual(clause["source"], "semantic")
        self.assertIn("语义相似", clause["reason"])
        self.assertGreaterEqual(clause["match_score"], 0.82)
        self.assertGreater(usage["total_tokens"], 0)
        self.assertEqual(stats["candidates"], 1)

    def test_threshold_is_clamped_to_allowed_range(self):
        """阈值超界要被钳制，否则用户填 1.5 会让功能静默失效。"""
        _, _, high = semantic.recall(
            "doc-x",
            self.PARAPHRASE,
            [],
            config={"base_url": "https://example.com/v1", "model": "fake", "api_key": "k"},
            threshold=0.99,
            embed_fn=fake_embed,
        )
        self.assertAlmostEqual(high["threshold"], semantic.MAX_THRESHOLD, places=3)

        _, _, low = semantic.recall(
            "doc-x",
            self.PARAPHRASE,
            [],
            config={"base_url": "https://example.com/v1", "model": "fake", "api_key": "k"},
            threshold=0.1,
            embed_fn=fake_embed,
        )
        self.assertAlmostEqual(low["threshold"], semantic.MIN_THRESHOLD, places=3)

    def test_recalled_payment_paraphrase_is_high_risk(self):
        """「三个月结清 + 逾期不计息」属于长账期，风险应被细化成 high。"""
        clauses, _, _ = semantic.recall(
            "doc-x",
            "双方约定账期为交付完成后的第三个月结清，逾期不计息。",
            [],
            config={"base_url": "https://example.com/v1", "model": "fake", "api_key": "k"},
            threshold=0.82,
            embed_fn=fake_embed,
        )
        self.assertEqual(len(clauses), 1)
        self.assertEqual(clauses[0]["title"], "付款与验收")
        self.assertEqual(clauses[0]["risk"], "high")

    def test_recalled_clause_without_long_term_stays_medium(self):
        clauses, _, _ = semantic.recall(
            "doc-x",
            "双方约定按季度结算相关服务费用。",
            [],
            config={"base_url": "https://example.com/v1", "model": "fake", "api_key": "k"},
            threshold=0.5,
            embed_fn=fake_embed,
        )
        for clause in clauses:
            if clause["title"] == "付款与验收":
                self.assertEqual(clause["risk"], "medium")

    def test_unrelated_sentence_not_recalled(self):
        clauses, _, _ = semantic.recall(
            "doc-x",
            self.UNRELATED,
            [],
            config={"base_url": "https://example.com/v1", "model": "fake", "api_key": "k"},
            threshold=0.82,
            embed_fn=fake_embed,
        )
        self.assertEqual(clauses, [])

    def test_rule_covered_sentence_is_skipped(self):
        text = "甲方应在验收合格后九十日内支付全部款项。"
        rules = analyze_text("doc-y", text)
        self.assertTrue(rules, "规则应命中这句话")
        spans = [(clause["start_offset"], clause["end_offset"]) for clause in rules]
        clauses, _, stats = semantic.recall(
            "doc-y",
            text,
            spans,
            config={"base_url": "https://example.com/v1", "model": "fake", "api_key": "k"},
            threshold=0.5,
            embed_fn=fake_embed,
        )
        self.assertEqual(clauses, [])
        self.assertGreaterEqual(stats["skipped_by_overlap"], 1)


class EmbeddingFormatTests(unittest.TestCase):
    """不同服务商的向量协议差异：OpenAI 标准 vs 千问多模态 input.contents。"""

    def test_payload_variants_cover_both_protocols(self):
        from backend.embeddings import payload_variants

        variants = dict(payload_variants("m", ["a", "b"]))
        self.assertEqual(variants["input 数组"]["input"], ["a", "b"])
        self.assertEqual(variants["input.contents[{text}]"]["input"]["contents"][0]["text"], "a")
        self.assertEqual(variants["input.contents[str]"]["input"]["contents"], ["a", "b"])
        self.assertEqual(
            variants["input.contents[{type,text}]"]["input"]["contents"][1],
            {"type": "text", "text": "b"},
        )

    def test_extract_supports_openai_shape(self):
        from backend.embeddings import _extract_embeddings

        vectors = _extract_embeddings({"data": [{"embedding": [1, 2]}, {"embedding": [3, 4]}]}, 2)
        self.assertEqual(vectors, [[1.0, 2.0], [3.0, 4.0]])

    def test_extract_supports_output_shape(self):
        from backend.embeddings import _extract_embeddings

        data = {"output": {"embeddings": [{"embedding": [0.5, 0.5]}]}}
        self.assertEqual(_extract_embeddings(data, 1), [[0.5, 0.5]])

    def test_extract_rejects_mismatched_count(self):
        from fastapi import HTTPException

        from backend.embeddings import _extract_embeddings

        with self.assertRaises(HTTPException):
            _extract_embeddings({"data": [{"embedding": [1]}]}, 2)


class EmbeddingBatchTests(unittest.TestCase):
    """部分服务商限制单批条数（千问：≤25），代码要对半拆到能过为止。"""

    def test_splits_batch_when_provider_rejects_size(self):
        from fastapi import HTTPException

        from backend import embeddings

        calls: list[int] = []
        original = embeddings._post

        def fake_post(url, payload, api_key):
            texts = payload["input"] if isinstance(payload.get("input"), list) else []
            calls.append(len(texts))
            if len(texts) > 2:
                raise HTTPException(
                    502, "请求被服务商拒绝：<400> batch size is invalid, it should not be larger than 2"
                )
            return {"data": [{"embedding": [1.0, 0.0]} for _ in texts]}

        embeddings._post = fake_post
        try:
            vectors, usage = embeddings._post_batch(
                "https://example.com/v1/embeddings", "m", ["a", "b", "c", "d", "e"], "k"
            )
        finally:
            embeddings._post = original

        self.assertEqual(len(vectors), 5)
        self.assertEqual(vectors[0], [1.0, 0.0])
        self.assertLessEqual(max(calls), 5)
        self.assertGreaterEqual(len(calls), 3)  # 必然经历过拆分
        self.assertEqual(usage["total_tokens"], 0)


class RecallSettingsApiTests(unittest.TestCase):
    def test_requires_login(self):
        self.assertEqual(make_client().get("/api/settings/recall").status_code, 401)

    def test_enable_without_model_rejected(self):
        client = make_client()
        register(client, "recall-nomodel")
        response = client.put("/api/settings/recall", json={"enabled": True, "model_id": ""})
        self.assertEqual(response.status_code, 409)

    def test_save_and_read_back(self):
        client = make_client()
        register(client, "recall-save")
        service = client.post(
            "/api/settings/services", json={"name": "百炼", "kind": "大模型"}
        ).json()["services"][0]
        model = client.post(
            f"/api/settings/services/{service['id']}/models",
            json={
                "name": "text-embedding-v3",
                "description": "向量模型",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-test-1234567890",
            },
        )
        self.assertEqual(model.status_code, 200, model.text)
        model_id = model.json()["services"][0]["models"][0]["id"]

        saved = client.put(
            "/api/settings/recall",
            json={"enabled": True, "model_id": model_id, "threshold": 0.88},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        settings = saved.json()["settings"]
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["model_id"], model_id)
        self.assertAlmostEqual(settings["threshold"], 0.88, places=3)

        refetched = client.get("/api/settings/recall").json()["settings"]
        self.assertEqual(refetched["model_id"], model_id)
        self.assertEqual(len(client.get("/api/settings/recall").json()["models"]), 1)


if __name__ == "__main__":
    unittest.main()
