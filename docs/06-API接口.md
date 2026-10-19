# 06 · API 接口

Base URL：`http://127.0.0.1:8103`

在线调试：启动后访问 http://127.0.0.1:8103/docs （FastAPI 自动生成，可直接试调用）。

## 通用约定

- **认证**：除 `/api/health`、`/api/auth/*` 外均需登录，凭据是 Cookie `cg_session`（httpOnly，浏览器自动携带）
- **编码**：`application/json; charset=utf-8`
- **未登录**：`401 {"detail": "请先登录"}`
- **越权访问不存在的资源**：`404`（不返回 403）
- **业务失败**：`{"detail": "中文可读原因"}`

## 健康检查

### GET /api/health

公开接口，用于存活探测。

```json
{ "status": "ok", "service": "clauseguard", "version": "2.0.0" }
```

## 认证

### POST /api/auth/register

```json
{ "account": "a@b.com", "password": "pass12345", "name": "小王" }
```

`account` 可以是邮箱，也可以是用户名（3–20 位，中文/字母/数字/下划线）。

成功返回 `200` 并种下 Cookie：

```json
{ "user": { "id": "user-1792...", "email": "a@b.com", "username": null, "name": "小王" } }
```

失败：`409` 账号已存在；`422` 账号格式不对 / 密码不满足策略（≥8 位且含大小写字母、数字、符号中的至少三类，不能是常见弱口令，不能包含账号名）。

### POST /api/auth/login

```json
{ "account": "a@b.com 或 用户名", "password": "pass12345" }
```

失败：`401` 账号或密码错误；`429` 失败次数过多（10 分钟内 8 次）。

### POST /api/auth/logout

删除服务端会话并清 Cookie，返回 `{"status":"logged_out"}`。

### GET /api/auth/me

```json
{ "user": { "id": "user-...", "email": "a@b.com", "name": "小王" } }
```

## 文档

### GET /api/documents

返回当前账号的全部未删除合同（含条款）。

```json
[
  {
    "id": "contract-01",
    "name": "供应商服务合同",
    "owner": "采购部",
    "status": "reviewed",
    "source_type": "text",
    "text_length": 131,
    "created_at": "2026-10-18 09:00:00",
    "clauses": [
      {
        "id": "contract-01-1",
        "document_id": "contract-01",
        "title": "付款与验收",
        "risk": "high",
        "excerpt": "甲方在收到...",
        "original": "甲方在收到乙方发票并验收合格后九十日内支付全部款项，逾期付款不承担利息或其他责任。",
        "reason": "付款条件偏长...",
        "recommend": "建议将付款周期调整为验收后 30 日...",
        "start_offset": 0,
        "end_offset": 41,
        "accepted": 0,
        "comment": ""
      }
    ]
  }
]
```

### POST /api/documents/upload

粘贴导入。

```json
{ "name": "某合同", "text": "正文，至少 20 字", "owner": "采购部" }
```

返回新建的文档对象（含空 clauses）。限制：文本 ≤ 30 万字符。

### POST /api/documents/upload-file

`multipart/form-data`，字段名 `file`。支持 `.txt` `.md` `.docx` `.pdf`，单文件 ≤ 8 MB。

```powershell
curl.exe -X POST http://127.0.0.1:8103/api/documents/upload-file `
  -b cookies.txt -F "file=@C:\path\合同.docx"
```

失败：`422` 不支持格式 / 解析后文本过短（扫描件）；`413` 超过 30 万字符。

### GET /api/documents/{id}/text

返回正文，供前端渲染高亮。

```json
{ "id": "contract-01", "name": "供应商服务合同", "text": "甲方在收到..." }
```

### DELETE /api/documents/{id}

软删除，返回 `{"status":"deleted"}`。删除后所有访问返回 404，审计保留。

## 审阅

### POST /api/documents/{id}/review

一次性返回结果（用于不支持 SSE 的客户端）。

```json
{
  "document": { "...": "同列表项" },
  "mode": "deepseek",
  "model_error": null,
  "model_meta": {
    "provider": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "usage": { "prompt_tokens": 800, "completion_tokens": 300, "total_tokens": 1100 },
    "duration_ms": 2100
  },
  "tool_calls": ["document_parser", "clause_detector", "risk_policy_engine"],
  "duration_ms": 2345.6
}
```

`mode` 为 `demo` 表示未调用模型（降级），`model_error` 给出原因。

### GET /api/documents/{id}/review/stream

**SSE**，`text/event-stream`。事件类型：

```
event: step
data: {"step":"读取文档","status":"success","detail":"131 字符 · 来源 text","duration_ms":0.3}

event: step
data: {"step":"条款切分","status":"success","detail":"识别 4 条候选条款","duration_ms":1.2}

event: step
data: {"step":"模型审阅","status":"running","detail":"deepseek-chat @ https://api.deepseek.com","duration_ms":0.1}

event: result
data: { ...同 POST /review 的完整响应... }
```

失败时：

```
event: error
data: {"detail":"Key 无效或已失效"}
```

注意：SSE 接口用 GET，因为 `EventSource` 不支持 POST；前端实际用 `fetch` + ReadableStream 解析。

## 条款处置

### POST /api/clauses/{id}/approve

```json
{ "accepted": true }
```

返回 `{ "status": "approved", "clause": { ...更新后的条款... } }`。

### POST /api/clauses/{id}/approve

```json
{ "accepted": true }
```

通过审批 → 状态变为 `approved`；传 `accepted: false` 等同于快速驳回。

### POST /api/clauses/{id}/reject

```json
{ "reason": "付款周期仍需与财务确认" }
```

驳回理由必填（1–500 字），写入审计。

### POST /api/clauses/{id}/execute

只有 `approved` 状态可以执行，否则返回 `409`：

```json
{ "status": "executed", "clause": { "...": "..." }, "replayed": false }
```

重复调用返回同一结果（`replayed: true`），可配合请求头 `Idempotency-Key` 做接口级重放。

### POST /api/clauses/{id}/comment

```json
{ "comment": "已与供应商确认改为 60 日" }
```

最长 1000 字。返回 `{ "status": "saved", "clause": {...} }`。

## 审计

### GET /api/documents/{id}/audit

```json
[
  { "id": 12, "action": "review", "payload": { "clauses": 4, "high": 2, "mode": "deepseek" },
    "created_at": "2026-10-19 10:00:00" },
  { "id": 11, "action": "upload", "payload": { "chars": 131, "source": "docx" },
    "created_at": "2026-10-19 09:59:00" }
]
```

## 报告

### GET /api/report/{id}

JSON 报告：`title` / `document` / `owner` / `summary` / `clauses`。

### GET /api/report/{id}/export?format=md|docx

返回文件流，带 `Content-Disposition: attachment; filename*=UTF-8''...`。

```powershell
curl.exe -OJ "http://127.0.0.1:8103/api/report/contract-01/export?format=docx" -b cookies.txt
```

## 模型设置

### GET /api/settings/services

```json
{
  "services": [
    {
      "id": "svc-1a2b3c",
      "name": "Qwen",
      "kind": "大模型",
      "models": [
        {
          "id": "mdl-9x8y7z",
          "name": "qwen-plus",
          "description": "通义千问",
          "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
          "key_hint": "sk-a…3456",
          "configured": true,
          "is_active": true,
          "verified_at": "2026-10-19 11:00:00"
        }
      ]
    }
  ],
  "presets": [{ "id": "preset-...", "label": "DeepSeek", "base_url": "https://api.deepseek.com" }],
  "kinds": ["大模型", "综合服务", "本地模型", "自定义"]
}
```

### POST /api/settings/services

```json
{ "name": "Qwen", "kind": "大模型" }
```

`409` 同名服务商已存在。

### PUT /api/settings/services/{id}

```json
{ "name": "Qwen 正式", "kind": "大模型" }
```

### DELETE /api/settings/services/{id}

级联删除该服务商下所有模型与 Key。

### POST /api/settings/services/{id}/models

```json
{
  "name": "qwen-plus",
  "description": "通义千问",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "api_key": "sk-xxx"
}
```

- `name`、`base_url` 必填；`api_key` 可留空（之后再补）
- `409` 同服务商下重名；`422` 地址不合法 / 内网地址 / 非 https

### PUT /api/settings/services/{id}/models/{mid}

同字段；`api_key` 留空表示保留原 Key。
**改了 `base_url` 又没有新 Key 时返回 409**，防止把旧 Key 发往新地址。

### DELETE /api/settings/services/{id}/models/{mid}

### POST /api/settings/services/{id}/models/{mid}/activate

设为「当前使用」，同用户其他模型自动取消。

### POST /api/settings/services/{id}/models/{mid}/test

真实调用 `POST {base_url}/chat/completions`，要求模型返回 `{"ok":true}`。

```json
{ "ok": true, "model": "qwen-plus", "duration_ms": 1234, "services": [ ... ] }
```

失败：`409` 未配置 Key；`502` 上游报错（消息会带服务商原始错误）。

### 模板

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/settings/presets | 列表 |
| POST | /api/settings/presets | `{label, base_url}` |
| PUT | /api/settings/presets/{id} | 同上 |
| DELETE | /api/settings/presets/{id} | 只删模板，不删服务商 |

## 错误码速查

| 状态码 | 含义 | 常见原因 |
| --- | --- | --- |
| 401 | 未登录 / 会话过期 | 没登录、7 天过期、清过 Cookie |
| 404 | 资源不存在或不属于当前账号 | 越权访问按 404 处理 |
| 409 | 冲突 | 重名、改地址未填 Key、邮箱已注册 |
| 413 | 内容过大 | 正文超 30 万字符 |
| 422 | 参数不合法 | URL 非法、内网地址、密码太短、文件格式不支持 |
| 429 | 频率限制 | 登录失败次数过多 |
| 502 | 上游错误 | 模型服务商返回错误 |
| 504 | 超时 | 模型服务不可达（90 秒） |
