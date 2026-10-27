"""模型调用用量统计（可观测性）测试。

覆盖：记录成功/失败、按模型聚合、用户隔离、HTTP 接口需要登录。
"""
import os
import tempfile
import time
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cg-llmstats-"))
os.environ.setdefault("CLAUSEGUARD_DB", str(TMP / "test.sqlite3"))
os.environ.setdefault("CLAUSEGUARD_DATA", str(TMP))
os.environ.setdefault("CLAUSEGUARD_ALLOW_PRIVATE_MODEL", "0")

from fastapi.testclient import TestClient  # noqa: E402

from backend import llm_stats  # noqa: E402
from backend.app import app  # noqa: E402


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


class RecordTests(unittest.TestCase):
    def test_success_and_failure_are_counted(self):
        user_id = f"user-{int(time.time() * 1000)}"
        llm_stats.record(
            user_id=user_id,
            purpose="review",
            model="test-model",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            duration_ms=1200,
        )
        llm_stats.record(
            user_id=user_id,
            purpose="review",
            model="test-model",
            duration_ms=300,
            ok=False,
            error="Key 无效或已失效",
        )

        data = llm_stats.summary(user_id, days=7)
        totals = data["totals"]
        self.assertEqual(totals["calls"], 2)
        self.assertEqual(totals["ok"], 1)
        self.assertEqual(totals["failed"], 1)
        self.assertEqual(totals["total_tokens"], 150)
        self.assertEqual(totals["avg_duration_ms"], 1200.0)
        self.assertEqual(len(data["by_model"]), 1)
        self.assertEqual(data["by_model"][0]["model"], "test-model")
        self.assertEqual(data["by_model"][0]["calls"], 2)
        self.assertEqual(len(data["by_day"]), 1)
        self.assertEqual(data["recent"][0]["ok"], False)
        self.assertIn("Key 无效", data["recent"][0]["error"])

    def test_users_are_isolated(self):
        left = f"left-{int(time.time() * 1000)}"
        right = f"right-{int(time.time() * 1000)}"
        llm_stats.record(user_id=left, purpose="review", model="m", usage={"total_tokens": 10})
        self.assertEqual(llm_stats.summary(left)["totals"]["calls"], 1)
        self.assertEqual(llm_stats.summary(right)["totals"]["calls"], 0)

    def test_record_never_raises_on_bad_usage(self):
        user_id = f"bad-{int(time.time() * 1000)}"
        llm_stats.record(user_id=user_id, purpose="review", usage={"total_tokens": "abc"})
        self.assertEqual(llm_stats.summary(user_id)["totals"]["total_tokens"], 0)


class MetricsEndpointTests(unittest.TestCase):
    def test_requires_login(self):
        self.assertEqual(make_client().get("/api/metrics/llm").status_code, 401)

    def test_returns_only_current_user(self):
        client = make_client()
        user = register(client, "metrics")
        llm_stats.record(
            user_id=user["id"],
            purpose="review",
            model="端点模型",
            usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            duration_ms=800,
        )
        llm_stats.record(user_id="someone-else", purpose="review", model="别人", duration_ms=100)

        body = client.get("/api/metrics/llm?days=7").json()
        self.assertEqual(body["totals"]["calls"], 1)
        self.assertEqual(body["totals"]["total_tokens"], 30)
        self.assertEqual(body["by_model"][0]["model"], "端点模型")
        self.assertEqual(body["days"], 7)


if __name__ == "__main__":
    unittest.main()
