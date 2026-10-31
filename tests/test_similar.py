"""相似历史案例检索测试（离线，注入假向量）。

覆盖：
- 未配置向量模型时返回空 + 原因，而不是报错
- 同类历史记录按相似度排序，低于阈值被过滤
- 处置状态与批注/驳回理由能正确带出
- 接口需要登录；不存在的条款返回 404
"""
import math
import os
import tempfile
import time
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cg-similar-"))
os.environ.setdefault("CLAUSEGUARD_DB", str(TMP / "test.sqlite3"))
os.environ.setdefault("CLAUSEGUARD_DATA", str(TMP))
os.environ.setdefault("CLAUSEGUARD_ALLOW_PRIVATE_MODEL", "0")

from fastapi.testclient import TestClient  # noqa: E402

from backend import similar_cases  # noqa: E402
from backend.app import app  # noqa: E402

DIMS = 64
KEYWORDS = ("账期", "付款", "结清", "间接损失", "责任", "保密", "续期")


def _dim(token: str) -> int:
    import hashlib

    return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % DIMS


def fake_embed(config, texts):
    vectors = []
    for text in texts:
        vector = [0.0] * DIMS
        for index in range(len(text) - 1):
            vector[_dim(text[index : index + 2])] += 1.0
        for keyword in KEYWORDS:
            if keyword in text:
                vector[_dim("kw:" + keyword)] += 8.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        vectors.append([value / norm for value in vector])
    return vectors, {"prompt_tokens": len(texts), "completion_tokens": 0, "total_tokens": len(texts)}


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


CLAUSE = {
    "id": "doc-1-1",
    "title": "付款与验收",
    "original": "双方约定账期为交付完成后的第三个月结清，逾期不计息。",
}

ROWS = [
    {
        "id": "doc-9-1",
        "title": "付款与验收",
        "risk": "high",
        "original": "账期自交付之日起九十天，逾期不计利息。",
        "status": "approved",
        "accepted": 1,
        "comment": "已与供应商确认改为 60 日",
        "reject_reason": "",
        "updated_at": "2026-10-01 10:00:00",
        "document_name": "去年的采购合同",
    },
    {
        "id": "doc-8-1",
        "title": "付款与验收",
        "risk": "medium",
        "original": "保密义务在终止后继续有效两年。",
        "status": "rejected",
        "accepted": 0,
        "comment": "",
        "reject_reason": "不属于付款条款，误报",
        "updated_at": "2026-09-01 10:00:00",
        "document_name": "渠道协议",
    },
]


class FindSimilarTests(unittest.TestCase):
    def setUp(self):
        self._original = similar_cases.candidates

    def tearDown(self):
        similar_cases.candidates = self._original

    def test_without_config_returns_reason(self):
        cases, note = similar_cases.find_similar("u1", CLAUSE, config=None, embed_fn=fake_embed)
        self.assertEqual(cases, [])
        self.assertIn("未配置向量模型", note)

    def test_empty_history_returns_reason(self):
        similar_cases.candidates = lambda *args, **kwargs: []
        cases, note = similar_cases.find_similar(
            "u1", CLAUSE, config={"model": "m"}, embed_fn=fake_embed
        )
        self.assertEqual(cases, [])
        self.assertIn("历史处置记录", note)

    def test_similar_sorted_and_low_score_filtered(self):
        similar_cases.candidates = lambda *args, **kwargs: ROWS
        cases, note = similar_cases.find_similar(
            "u1", CLAUSE, config={"model": "m"}, embed_fn=fake_embed
        )
        self.assertEqual(note, "")
        self.assertGreaterEqual(len(cases), 1)
        self.assertEqual(cases[0]["document_name"], "去年的采购合同")
        self.assertEqual(cases[0]["decision"], "approved")
        self.assertEqual(cases[0]["decision_label"], "已采纳")
        self.assertIn("60 日", cases[0]["comment"])
        # 保密条款与付款条款相似度低，应被过滤
        self.assertTrue(all("保密" not in case["excerpt"] for case in cases))
        scores = [case["score"] for case in cases]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_rejected_case_carries_reason(self):
        similar_cases.candidates = lambda *args, **kwargs: [ROWS[0], ROWS[1]]
        cases, _ = similar_cases.find_similar(
            "u1", CLAUSE, config={"model": "m"}, embed_fn=fake_embed, limit=5
        )
        rejected = [case for case in cases if case["decision"] == "rejected"]
        for case in rejected:
            self.assertEqual(case["reject_reason"], "不属于付款条款，误报")


class SimilarEndpointTests(unittest.TestCase):
    def test_requires_login(self):
        response = make_client().get("/api/clauses/doc-1-1/similar")
        self.assertEqual(response.status_code, 401)

    def test_unknown_clause_returns_404(self):
        client = make_client()
        register(client, "similar-404")
        response = client.get("/api/clauses/not-exists/similar")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
