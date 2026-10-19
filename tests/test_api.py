"""API 与多租户隔离测试。

用独立的临时数据库，不碰开发库。
重点覆盖：未登录拒绝、注册登录、越权访问返回 404、密钥不回显、导出与删除。
"""
import os
import tempfile
import time
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cg-test-"))
os.environ["CLAUSEGUARD_DB"] = str(TMP / "test.sqlite3")
os.environ["CLAUSEGUARD_DATA"] = str(TMP)
os.environ["CLAUSEGUARD_ALLOW_PRIVATE_MODEL"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402

CONTRACT = (
    "甲方应在验收合格后九十日内支付全部款项，逾期付款不承担利息。"
    "乙方在任何情况下不对间接损失、预期利润损失承担责任。"
    "任一方未在合同期限届满前三十日书面通知终止的，本合同自动续期一年。"
)


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


class AuthTests(unittest.TestCase):
    def test_health_is_public(self):
        self.assertEqual(make_client().get("/api/health").status_code, 200)

    def test_documents_require_login(self):
        self.assertEqual(make_client().get("/api/documents").status_code, 401)

    def test_register_login_logout(self):
        client = make_client()
        user = register(client, "auth")
        self.assertEqual(client.get("/api/auth/me").json()["user"]["email"], user["email"])

        client.post("/api/auth/logout")
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

        response = client.post(
            "/api/auth/login", json={"account": user["email"], "password": "Passw0rd!"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/api/auth/me").status_code, 200)

    def test_wrong_password_rejected(self):
        client = make_client()
        user = register(client, "wrongpw")
        make_client()
        fresh = make_client()
        response = fresh.post(
            "/api/auth/login", json={"account": user["email"], "password": "nope-nope"}
        )
        self.assertEqual(response.status_code, 401)

    def test_duplicate_email_rejected(self):
        client = make_client()
        user = register(client, "dup")
        response = make_client().post(
            "/api/auth/register", json={"account": user["email"], "password": "Passw0rd!"}
        )
        self.assertEqual(response.status_code, 409)


class TenantIsolationTests(unittest.TestCase):
    def setUp(self):
        self.alice = make_client()
        register(self.alice, "alice")
        self.bob = make_client()
        register(self.bob, "bob")

    def test_new_user_starts_empty(self):
        self.assertEqual(self.alice.get("/api/documents").json(), [])

    def test_cannot_read_other_users_document(self):
        created = self.alice.post(
            "/api/documents/upload", json={"name": "A 的合同", "text": CONTRACT}
        ).json()
        self.assertEqual(self.bob.get(f"/api/documents/{created['id']}/text").status_code, 404)
        self.assertEqual(self.bob.get(f"/api/report/{created['id']}").status_code, 404)
        self.assertEqual(self.bob.delete(f"/api/documents/{created['id']}").status_code, 404)

    def test_cannot_review_other_users_document(self):
        created = self.alice.post(
            "/api/documents/upload", json={"name": "A 的合同 2", "text": CONTRACT}
        ).json()
        self.assertEqual(
            self.bob.post(f"/api/documents/{created['id']}/review").status_code, 404
        )

    def test_cannot_touch_other_users_clause(self):
        created = self.alice.post(
            "/api/documents/upload", json={"name": "A 的合同 3", "text": CONTRACT}
        ).json()
        reviewed = self.alice.post(f"/api/documents/{created['id']}/review").json()
        clause_id = reviewed["document"]["clauses"][0]["id"]
        self.assertEqual(
            self.bob.post(f"/api/clauses/{clause_id}/approve", json={"accepted": True}).status_code,
            404,
        )
        self.assertEqual(
            self.bob.post(f"/api/clauses/{clause_id}/comment", json={"comment": "x"}).status_code,
            404,
        )

    def test_document_lists_are_separate(self):
        self.alice.post("/api/documents/upload", json={"name": "A 独有", "text": CONTRACT})
        names = [item["name"] for item in self.bob.get("/api/documents").json()]
        self.assertNotIn("A 独有", names)


class ReviewFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = make_client()
        register(self.client, "flow")
        self.doc = self.client.post(
            "/api/documents/upload", json={"name": "流程合同", "text": CONTRACT}
        ).json()

    def test_review_produces_clauses_with_aligned_offsets(self):
        result = self.client.post(f"/api/documents/{self.doc['id']}/review").json()
        clauses = result["document"]["clauses"]
        self.assertGreaterEqual(len(clauses), 3)
        self.assertEqual(result["mode"], "demo")

        text = self.client.get(f"/api/documents/{self.doc['id']}/text").json()["text"]
        for clause in clauses:
            self.assertEqual(
                text[clause["start_offset"]: clause["end_offset"]],
                clause["original"],
                clause["title"],
            )

    def test_approve_and_comment_persist_across_review(self):
        result = self.client.post(f"/api/documents/{self.doc['id']}/review").json()
        clause = result["document"]["clauses"][0]

        self.client.post(f"/api/clauses/{clause['id']}/approve", json={"accepted": True})
        self.client.post(
            f"/api/clauses/{clause['id']}/comment", json={"comment": "已和法务确认"}
        )

        again = self.client.post(f"/api/documents/{self.doc['id']}/review").json()
        kept = [c for c in again["document"]["clauses"] if c["title"] == clause["title"]][0]
        self.assertEqual(kept["accepted"], 1)
        self.assertEqual(kept["comment"], "已和法务确认")

    def test_audit_log_records_actions(self):
        self.client.post(f"/api/documents/{self.doc['id']}/review")
        logs = self.client.get(f"/api/documents/{self.doc['id']}/audit").json()
        actions = {item["action"] for item in logs}
        self.assertIn("upload", actions)
        self.assertIn("review", actions)

    def test_export_markdown_and_docx(self):
        self.client.post(f"/api/documents/{self.doc['id']}/review")
        markdown = self.client.get(f"/api/report/{self.doc['id']}/export?format=md")
        self.assertEqual(markdown.status_code, 200)
        self.assertIn("审阅报告", markdown.text)

        docx = self.client.get(f"/api/report/{self.doc['id']}/export?format=docx")
        self.assertEqual(docx.status_code, 200)
        self.assertEqual(docx.content[:2], b"PK")

    def test_delete_hides_document(self):
        self.assertEqual(
            self.client.delete(f"/api/documents/{self.doc['id']}").status_code, 200
        )
        listed = [item["id"] for item in self.client.get("/api/documents").json()]
        self.assertNotIn(self.doc["id"], listed)
        self.assertEqual(
            self.client.get(f"/api/documents/{self.doc['id']}/text").status_code, 404
        )


class ModelConfigTests(unittest.TestCase):
    def setUp(self):
        self.client = make_client()
        register(self.client, "model")

    def create_service(self, name="Qwen", kind="大模型"):
        response = self.client.post("/api/settings/services", json={"name": name, "kind": kind})
        self.assertEqual(response.status_code, 200, response.text)
        return [s for s in response.json()["services"] if s["name"] == name][-1]

    def test_presets_and_kinds_seeded(self):
        body = self.client.get("/api/settings/services").json()
        self.assertGreaterEqual(len(body["presets"]), 5)
        self.assertIn("大模型", body["kinds"])

    def test_service_only_needs_name_and_kind(self):
        service = self.create_service()
        self.assertEqual(service["models"], [])
        self.assertEqual(service["kind"], "大模型")

    def test_model_carries_its_own_address_and_key(self):
        service = self.create_service()
        added = self.client.post(
            f"/api/settings/services/{service['id']}/models",
            json={
                "name": "qwen-plus",
                "description": "对话模型",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-secret-value-123456",
            },
        )
        self.assertEqual(added.status_code, 200, added.text)
        self.assertNotIn("sk-secret-value-123456", added.text)
        model = added.json()["services"][0]["models"][0]
        self.assertTrue(model["configured"])
        self.assertTrue(model["key_hint"].endswith("3456"))
        self.assertTrue(model["is_active"])

    def test_second_model_needs_no_key_duplicate(self):
        service = self.create_service()
        base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        for name in ("qwen-plus", "qwen-max"):
            response = self.client.post(
                f"/api/settings/services/{service['id']}/models",
                json={"name": name, "base_url": base, "api_key": "sk-abc-123456"},
            )
            self.assertEqual(response.status_code, 200, response.text)
        models = self.client.get("/api/settings/services").json()["services"][0]["models"]
        self.assertEqual([m["name"] for m in models], ["qwen-plus", "qwen-max"])
        self.assertEqual(sum(1 for m in models if m["is_active"]), 1)

    def test_private_address_rejected(self):
        service = self.create_service()
        response = self.client.post(
            f"/api/settings/services/{service['id']}/models",
            json={"name": "local", "base_url": "http://127.0.0.1:11434/v1", "api_key": "sk-x"},
        )
        self.assertEqual(response.status_code, 422)

    def test_deleting_service_removes_models(self):
        service = self.create_service()
        self.client.post(
            f"/api/settings/services/{service['id']}/models",
            json={"name": "m1", "base_url": "https://api.deepseek.com", "api_key": "sk-1"},
        )
        removed = self.client.delete(f"/api/settings/services/{service['id']}")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["services"], [])

    def test_services_are_isolated_between_users(self):
        self.create_service("OnlyMine")
        other = make_client()
        register(other, "model-other")
        self.assertEqual(other.get("/api/settings/services").json()["services"], [])

    def test_other_user_cannot_touch_service(self):
        service = self.create_service()
        other = make_client()
        register(other, "model-other2")
        self.assertEqual(other.delete(f"/api/settings/services/{service['id']}").status_code, 404)


class ClauseWorkflowTests(unittest.TestCase):
    """审批门禁与幂等执行。"""

    def setUp(self):
        self.client = make_client()
        register(self.client, "wf")
        doc = self.client.post(
            "/api/documents/upload", json={"name": "状态机合同", "text": CONTRACT}
        ).json()
        result = self.client.post(f"/api/documents/{doc['id']}/review").json()
        self.clause = result["document"]["clauses"][0]

    def state(self, clause_id):
        return self.client.get("/api/documents").json()[0]["clauses"]

    def test_execute_requires_approval(self):
        response = self.client.post(f"/api/clauses/{self.clause['id']}/execute")
        self.assertEqual(response.status_code, 409)
        self.assertIn("审批", response.json()["detail"])

    def test_approve_then_execute(self):
        approved = self.client.post(f"/api/clauses/{self.clause['id']}/approve", json={"accepted": True})
        self.assertEqual(approved.json()["status"], "approved")

        executed = self.client.post(f"/api/clauses/{self.clause['id']}/execute")
        self.assertEqual(executed.json()["status"], "executed")
        self.assertEqual(executed.json()["clause"]["status"], "executed")

    def test_execute_is_idempotent(self):
        self.client.post(f"/api/clauses/{self.clause['id']}/approve", json={"accepted": True})
        first = self.client.post(f"/api/clauses/{self.clause['id']}/execute").json()
        second = self.client.post(f"/api/clauses/{self.clause['id']}/execute").json()
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(first["clause"]["executed_at"], second["clause"]["executed_at"])

    def test_reject_requires_reason(self):
        response = self.client.post(f"/api/clauses/{self.clause['id']}/reject", json={"reason": ""})
        self.assertEqual(response.status_code, 422)

    def test_rejected_cannot_execute(self):
        self.client.post(
            f"/api/clauses/{self.clause['id']}/reject", json={"reason": "条款描述不符"}
        )
        response = self.client.post(f"/api/clauses/{self.clause['id']}/execute")
        self.assertEqual(response.status_code, 409)

    def test_executed_cannot_be_rejected(self):
        self.client.post(f"/api/clauses/{self.clause['id']}/approve", json={"accepted": True})
        self.client.post(f"/api/clauses/{self.clause['id']}/execute")
        response = self.client.post(
            f"/api/clauses/{self.clause['id']}/reject", json={"reason": "反悔"}
        )
        self.assertEqual(response.status_code, 409)

    def test_status_survives_review(self):
        self.client.post(f"/api/clauses/{self.clause['id']}/approve", json={"accepted": True})
        docs = self.client.get("/api/documents").json()
        result = self.client.post(f"/api/documents/{docs[0]['id']}/review").json()
        kept = [c for c in result["document"]["clauses"] if c["title"] == self.clause["title"]][0]
        self.assertEqual(kept["status"], "approved")


if __name__ == "__main__":
    unittest.main()