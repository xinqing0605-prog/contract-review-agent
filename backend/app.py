"""ClauseGuard 后端入口。

分层：
- security.py     密码哈希 / 会话令牌 / Key 加密
- db.py           建表、迁移、演示数据
- auth.py         注册登录与会话依赖
- model_config.py 每个用户自己的模型配置（含 SSRF 校验）
- provider.py     OpenAI 兼容客户端
- ingest.py       文件解析（PDF / Word / 文本）
- detector.py     条款检测规则（可评测）
- app.py          业务编排与 HTTP 接口（本文件）

多租户：所有文档类接口都必须经过 owned_document / owned_clause 校验归属，
跨用户访问统一返回 404（不暴露 id 是否存在）。
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, db, model_config
from .auth import current_user
from .detector import analyze_text  # noqa: F401  re-export 给测试
from .ingest import extract_text

ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_CHARS = 300_000
MAX_COMMENT_CHARS = 1000
WEB_DIST = ROOT / "web" / "dist"

db.init()

app = FastAPI(title="ClauseGuard", version="2.0.0")
app.include_router(auth.router)
app.include_router(model_config.router)


# --------------------------------------------------------------------------- 安全响应头
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/") and not request.url.path.endswith("/stream"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# --------------------------------------------------------------------------- 模型
class UploadRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=20, max_length=MAX_TEXT_CHARS)
    owner: str = "当前用户"


class ApproveRequest(BaseModel):
    accepted: bool = True


class CommentRequest(BaseModel):
    comment: str = Field(default="", max_length=MAX_COMMENT_CHARS)


# --------------------------------------------------------------------------- 归属校验
CLAUSE_FIELDS = (
    "id, document_id, title, risk, excerpt, original, reason, recommend, "
    "start_offset, end_offset, accepted, COALESCE(comment,'') AS comment"
)


def owned_document(doc_id: str, user_id: str) -> dict[str, Any]:
    with db.tx() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id=? AND user_id=? AND COALESCE(deleted,0)=0",
            (doc_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "document not found")
    return dict(row)


def owned_clause(clause_id: str, user_id: str) -> dict[str, Any]:
    with db.tx() as conn:
        row = conn.execute(
            "SELECT c.* FROM clauses c JOIN documents d ON d.id = c.document_id "
            "WHERE c.id=? AND d.user_id=? AND COALESCE(d.deleted,0)=0",
            (clause_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "clause not found")
    return dict(row)


def doc_payload(doc_id: str, user_id: str, with_clauses: bool = True) -> dict[str, Any]:
    document = owned_document(doc_id, user_id)
    payload = {
        "id": document["id"],
        "name": document["name"],
        "owner": document["owner"],
        "status": document["status"],
        "source_type": document["source_type"] or "text",
        "text_length": len(document["text"] or ""),
        "created_at": document["created_at"],
    }
    if with_clauses:
        with db.tx() as conn:
            payload["clauses"] = [
                dict(row)
                for row in conn.execute(
                    f"SELECT {CLAUSE_FIELDS} FROM clauses WHERE document_id=? ORDER BY start_offset",
                    (doc_id,),
                ).fetchall()
            ]
    return payload


def audit(doc_id: str, user_id: str, action: str, payload: dict[str, Any]) -> None:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO review_audit(document_id,user_id,action,payload) VALUES(?,?,?,?)",
            (doc_id, user_id, action, json.dumps(payload, ensure_ascii=False)),
        )


# --------------------------------------------------------------------------- 审阅编排
def _step(name: str, status: str, detail: str, started: float) -> dict[str, Any]:
    return {
        "event": "step",
        "data": {
            "step": name,
            "status": status,
            "detail": detail,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }


def _review_events(doc_id: str, user: dict[str, Any]) -> Iterator[dict[str, Any]]:
    started = time.perf_counter()
    document = owned_document(doc_id, user["id"])
    text: str = document["text"] or ""
    source = document["source_type"] or "text"
    yield _step("读取文档", "success", f"{len(text)} 字符 · 来源 {source}", started)

    tick = time.perf_counter()
    clauses = analyze_text(doc_id, text)
    yield _step("条款切分", "success", f"识别 {len(clauses)} 条候选条款", tick)

    config = model_config.load_config(user["id"])
    mode, model_error, model_meta = "demo", None, None

    if clauses and config and config.get("api_key"):
        tick = time.perf_counter()
        yield _step("模型审阅", "running", f"{config['model']} @ {config['base_url']}", tick)
        try:
            from .provider import complete_json

            ai, model_meta = complete_json(
                config,
                "你是合同条款审阅助手。根据原文和候选条款输出 JSON 对象，格式为"
                '{"clauses":[{"id":"原候选id","risk":"high","reason":"风险解释","recommend":"修改建议"}]}。'
                "只能使用提供的候选 id；风险级别只能是 high、medium、low。"
                "保持审慎，不能编造原文和法律结论。",
                {
                    "document_name": document["name"],
                    "candidates": [
                        {"id": clause["id"], "title": clause["title"], "excerpt": clause["original"]}
                        for clause in clauses
                    ],
                },
                max_tokens=2200,
            )
            mapped = {
                item.get("id"): item
                for item in ai.get("clauses", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            for clause in clauses:
                item = mapped.get(clause["id"], {})
                for field in ("reason", "recommend"):
                    value = item.get(field)
                    if isinstance(value, str) and 0 < len(value) <= 1000:
                        clause[field] = value
            mode = "deepseek"
            usage = (model_meta or {}).get("usage") or {}
            yield _step(
                "模型审阅",
                "success",
                f"{(model_meta or {}).get('model', config['model'])} · "
                f"{usage.get('total_tokens', 0)} tokens · {(model_meta or {}).get('duration_ms', 0)} ms",
                tick,
            )
        except HTTPException as exc:
            model_error = str(exc.detail)
            yield _step("模型审阅", "skipped", f"{model_error}，已降级为规则解释", tick)
    else:
        yield _step("模型审阅", "skipped", "未配置模型，使用规则解释", time.perf_counter())

    high = sum(1 for clause in clauses if clause["risk"] == "high")
    medium = sum(1 for clause in clauses if clause["risk"] == "medium")
    yield _step(
        "风险分级", "success", f"高 {high} / 中 {medium} / 低 {len(clauses) - high - medium}",
        time.perf_counter(),
    )

    with db.tx() as conn:
        previous = {
            item["title"]: (item["accepted"], item["comment"] or "")
            for item in conn.execute(
                "SELECT title, accepted, COALESCE(comment,'') AS comment FROM clauses WHERE document_id=?",
                (doc_id,),
            ).fetchall()
        }
        for clause in clauses:
            accepted, comment = previous.get(clause["title"], (0, ""))
            clause["accepted"] = accepted
            clause["comment"] = comment

        conn.execute("DELETE FROM clauses WHERE document_id=?", (doc_id,))
        conn.executemany(
            "INSERT INTO clauses(id,document_id,title,risk,excerpt,original,reason,recommend,"
            "start_offset,end_offset,accepted,comment,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
            [
                (
                    clause["id"], clause["document_id"], clause["title"], clause["risk"],
                    clause["excerpt"], clause["original"], clause["reason"], clause["recommend"],
                    clause["start_offset"], clause["end_offset"], clause["accepted"], clause["comment"],
                )
                for clause in clauses
            ],
        )
        conn.execute("UPDATE documents SET status='reviewed' WHERE id=?", (doc_id,))

    used_model = "规则"
    if mode == "model" and model_meta:
        used_model = model_meta.get("model") or (config or {}).get("model") or "模型"
    elif mode == "model":
        used_model = (config or {}).get("model") or "模型"
    audit(
        doc_id,
        user["id"],
        "review",
        {"clauses": len(clauses), "model": used_model, "high": high, "mode": mode},
    )
    kept = sum(1 for clause in clauses if clause["accepted"] or clause["comment"])
    detail = f"已写入，保留 {kept} 条人工处置" if kept else "已写入，等待人工确认"
    yield _step("生成建议", "success", detail, time.perf_counter())

    yield {
        "event": "result",
        "data": {
            "document": doc_payload(doc_id, user["id"]),
            "mode": mode,
            "model_error": model_error,
            "model_meta": model_meta,
            "tool_calls": ["document_parser", "clause_detector", "risk_policy_engine"],
            "kept": kept,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }


# --------------------------------------------------------------------------- 路由
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "clauseguard", "version": "2.0.0"}


@app.get("/api/documents")
def documents(user: dict = Depends(current_user)) -> list[dict[str, Any]]:
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT id FROM documents WHERE user_id=? AND COALESCE(deleted,0)=0 "
            "ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()
    return [doc_payload(row["id"], user["id"]) for row in rows]


@app.post("/api/documents/upload")
def upload(body: UploadRequest, user: dict = Depends(current_user)) -> dict[str, Any]:
    doc_id = f"doc-{int(time.time() * 1000)}"
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO documents(id,user_id,name,owner,text,source_type) VALUES(?,?,?,?,?,'text')",
            (doc_id, user["id"], body.name, body.owner, body.text),
        )
    audit(doc_id, user["id"], "upload", {"chars": len(body.text), "source": "text"})
    return doc_payload(doc_id, user["id"])


@app.post("/api/documents/upload-file")
async def upload_file(
    file: UploadFile = File(...), user: dict = Depends(current_user)
) -> dict[str, Any]:
    payload = await file.read()
    try:
        source, text = extract_text(file.filename or "upload.txt", payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(413, f"解析后 {len(text)} 字符，超过 {MAX_TEXT_CHARS} 上限")

    doc_id = f"doc-{int(time.time() * 1000)}"
    directory = db.UPLOAD_DIR / user["id"]
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{doc_id}.{source}"
    target.write_bytes(payload)
    relative = str(target.relative_to(db.DATA_DIR))

    with db.tx() as conn:
        conn.execute(
            "INSERT INTO documents(id,user_id,name,owner,text,source_type,file_path) "
            "VALUES(?,?,?,?,?,?,?)",
            (doc_id, user["id"], Path(file.filename or "未命名").stem, "当前用户", text, source, relative),
        )
    audit(doc_id, user["id"], "upload", {"chars": len(text), "source": source})
    return doc_payload(doc_id, user["id"])


@app.get("/api/documents/{doc_id}/text")
def document_text(doc_id: str, user: dict = Depends(current_user)) -> dict[str, Any]:
    document = owned_document(doc_id, user["id"])
    return {"id": document["id"], "name": document["name"], "text": document["text"]}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, user: dict = Depends(current_user)) -> dict[str, str]:
    owned_document(doc_id, user["id"])
    with db.tx() as conn:
        conn.execute("UPDATE documents SET deleted=1 WHERE id=?", (doc_id,))
    audit(doc_id, user["id"], "delete", {})
    return {"status": "deleted"}


@app.post("/api/documents/{doc_id}/review")
def review(doc_id: str, user: dict = Depends(current_user)) -> dict[str, Any]:
    result: dict[str, Any] | None = None
    for item in _review_events(doc_id, user):
        if item["event"] == "result":
            result = item["data"]
    if result is None:  # pragma: no cover
        raise HTTPException(500, "审阅未产出结果")
    return result


@app.get("/api/documents/{doc_id}/review/stream")
def review_stream(doc_id: str, user: dict = Depends(current_user)) -> StreamingResponse:
    def events() -> Iterator[str]:
        try:
            for item in _review_events(doc_id, user):
                yield f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
        except HTTPException as exc:
            yield f"event: error\ndata: {json.dumps({'detail': exc.detail}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/clauses/{clause_id}/approve")
def approve_clause(
    clause_id: str, body: ApproveRequest, user: dict = Depends(current_user)
) -> dict[str, Any]:
    clause = owned_clause(clause_id, user["id"])
    with db.tx() as conn:
        conn.execute(
            "UPDATE clauses SET accepted=?, updated_at=datetime('now') WHERE id=?",
            (int(body.accepted), clause_id),
        )
        updated = conn.execute(f"SELECT {CLAUSE_FIELDS} FROM clauses WHERE id=?", (clause_id,)).fetchone()
    audit(
        clause["document_id"], user["id"],
        "approve_clause" if body.accepted else "reject_clause",
        {"clause_id": clause_id, "title": clause["title"]},
    )
    return {"status": "approved" if body.accepted else "rejected", "clause": dict(updated)}


@app.post("/api/clauses/{clause_id}/comment")
def comment_clause(
    clause_id: str, body: CommentRequest, user: dict = Depends(current_user)
) -> dict[str, Any]:
    clause = owned_clause(clause_id, user["id"])
    with db.tx() as conn:
        conn.execute(
            "UPDATE clauses SET comment=?, updated_at=datetime('now') WHERE id=?",
            (body.comment.strip(), clause_id),
        )
        updated = conn.execute(f"SELECT {CLAUSE_FIELDS} FROM clauses WHERE id=?", (clause_id,)).fetchone()
    audit(clause["document_id"], user["id"], "comment_clause", {"clause_id": clause_id})
    return {"status": "saved", "clause": dict(updated)}


@app.get("/api/documents/{doc_id}/audit")
def document_audit(doc_id: str, user: dict = Depends(current_user)) -> list[dict[str, Any]]:
    owned_document(doc_id, user["id"])
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT id,action,payload,created_at FROM review_audit "
            "WHERE document_id=? AND user_id=? ORDER BY id DESC",
            (doc_id, user["id"]),
        ).fetchall()
    events = []
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        events.append(
            {"id": row["id"], "action": row["action"], "payload": payload, "created_at": row["created_at"]}
        )
    return events


DISPOSITION = {"high": "高风险", "medium": "中风险", "low": "低风险"}


@app.get("/api/report/{doc_id}")
def report(doc_id: str, user: dict = Depends(current_user)) -> dict[str, Any]:
    document = doc_payload(doc_id, user["id"])
    clauses = document["clauses"]
    high = sum(1 for clause in clauses if clause["risk"] == "high")
    return {
        "title": "ClauseGuard 审阅报告",
        "document": document["name"],
        "owner": document["owner"],
        "summary": f"共识别 {len(clauses)} 条条款，其中高风险 {high} 条，"
        f"已确认 {sum(1 for clause in clauses if clause['accepted'])} 条。",
        "clauses": clauses,
    }


@app.get("/api/report/{doc_id}/export")
def export_report(doc_id: str, format: str = "md", user: dict = Depends(current_user)) -> Response:
    document = doc_payload(doc_id, user["id"])
    clauses = document["clauses"]
    high = sum(1 for clause in clauses if clause["risk"] == "high")
    summary = (
        f"共识别 {len(clauses)} 条条款，其中高风险 {high} 条，"
        f"已确认 {sum(1 for clause in clauses if clause['accepted'])} 条。"
    )
    name = document["name"]

    if format == "docx":
        try:
            from docx import Document
        except ImportError:  # pragma: no cover
            raise HTTPException(500, "服务端缺少 python-docx") from None
        word = Document()
        word.add_heading("合同审阅报告", level=0)
        word.add_paragraph(f"合同名称：{name}")
        word.add_paragraph(f"负责部门：{document['owner']}")
        word.add_paragraph(f"审阅结论：{summary}")
        for clause in clauses:
            word.add_heading(clause["title"], level=2)
            word.add_paragraph(f"风险等级：{DISPOSITION.get(clause['risk'], clause['risk'])}")
            word.add_paragraph(f"原文片段：{clause['original']}")
            word.add_paragraph(f"风险解释：{clause['reason']}")
            word.add_paragraph(f"修改建议：{clause['recommend']}")
            word.add_paragraph(
                f"处置结果：{'已采纳' if clause['accepted'] else '未处置'}"
                + (f"；批注：{clause['comment']}" if clause["comment"] else "")
            )
        buffer = io.BytesIO()
        word.save(buffer)
        return Response(
            content=buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'{name}-审阅报告.docx')}"
            },
        )

    lines = [
        f"# {name} · 审阅报告",
        "",
        f"- 负责部门：{document['owner']}",
        f"- 审阅结论：{summary}",
        "",
        "| 条款 | 风险 | 处置 | 批注 |",
        "| --- | --- | --- | --- |",
    ]
    for clause in clauses:
        lines.append(
            f"| {clause['title']} | {DISPOSITION.get(clause['risk'], clause['risk'])} "
            f"| {'已采纳' if clause['accepted'] else '未处置'} | {clause['comment'] or '-'} |"
        )
    lines.append("")
    for index, clause in enumerate(clauses, 1):
        lines += [
            f"## {index}. {clause['title']}（{DISPOSITION.get(clause['risk'], clause['risk'])}）",
            "",
            f"> {clause['original']}",
            "",
            f"**风险**：{clause['reason']}",
            "",
            f"**建议**：{clause['recommend']}",
            "",
        ]
    return Response(
        content="\n".join(lines).encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'{name}-审阅报告.md')}"},
    )


# --------------------------------------------------------------------------- 前端静态资源
if WEB_DIST.exists():
    assets = WEB_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        candidate = (WEB_DIST / path).resolve()
        if path and candidate.is_file() and WEB_DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
