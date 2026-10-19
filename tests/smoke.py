"""真实 HTTP 服务的冒烟测试：验证 Cookie 会话与 SSE 在真实网络栈下可用。

TestClient 走的是进程内调用，会话 Cookie 和流式响应都要在真实服务器上再验一次。
"""
import json
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

BASE = "http://127.0.0.1:8103"
jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
failures: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' · ' + extra) if extra else ''}")
    if not ok:
        failures.append(name)


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with opener.open(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


print("=== 未登录 ===")
status, _ = call("GET", "/api/documents")
check("未登录访问被拒 401", status == 401, str(status))

print("\n=== 注册并建立会话 ===")
email = f"smoke-{int(time.time() * 1000)}@test.local"
status, payload = call("POST", "/api/auth/register",
                       {"email": email, "password": "pass12345", "name": "冒烟"})
check("注册成功", status == 200, payload.decode()[:60])
check("拿到了会话 Cookie", any(c.name == "cg_session" for c in jar), str([c.name for c in jar]))

status, payload = call("GET", "/api/auth/me")
check("会话有效", status == 200 and json.loads(payload)["user"]["email"] == email)

status, payload = call("GET", "/api/documents")
check("新用户文档为空（数据隔离）", status == 200 and json.loads(payload) == [])

print("\n=== 导入与 SSE 流式审阅 ===")
contract = (
    "甲方应在收到发票并验收合格后九十日内支付全部款项，逾期付款不承担利息。"
    "乙方在任何情况下不对间接损失、预期利润损失承担责任。"
    "任一方未在合同期限届满前三十日书面通知终止的，本合同自动续期一年。"
)
status, payload = call("POST", "/api/documents/upload", {"name": "冒烟合同", "text": contract})
doc = json.loads(payload)
check("导入成功", status == 200 and doc.get("id"), doc.get("id", ""))

req = urllib.request.Request(f"{BASE}/api/documents/{doc['id']}/review/stream", method="GET")
events, current = [], {}
with opener.open(req, timeout=60) as resp:
    content_type = resp.headers.get("Content-Type", "")
    for raw in resp:
        line = raw.decode("utf-8").rstrip("\n")
        if line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
        elif line == "" and current:
            events.append(current)
            current = {}
check("SSE Content-Type 正确", "text/event-stream" in content_type, content_type)
steps = [e for e in events if e["event"] == "step"]
result = next((e["data"] for e in events if e["event"] == "result"), None)
check("收到流式步骤", len(steps) >= 4, f"{len(steps)} 步")
check("收到最终结果", result is not None)
if result:
    clauses = result["document"]["clauses"]
    check("条款已落库", len(clauses) >= 2, f"{len(clauses)} 条")
    status, text_payload = call("GET", f"/api/documents/{doc['id']}/text")
    text = json.loads(text_payload)["text"]
    aligned = all(text[c["start_offset"]:c["end_offset"]] == c["original"] for c in clauses)
    check("偏移量对齐", aligned)

print("\n=== 导出与登出 ===")
status, payload = call("GET", f"/api/report/{doc['id']}/export?format=md")
check("导出 Markdown", status == 200 and "审阅报告" in payload.decode("utf-8"), f"{len(payload)} 字节")

status, _ = call("POST", "/api/auth/logout")
check("登出成功", status == 200)
status, _ = call("GET", "/api/documents")
check("登出后会话失效", status == 401, str(status))

print("\n" + ("全部通过" if not failures else f"失败 {len(failures)} 项：" + "；".join(failures)))
sys.exit(1 if failures else 0)
