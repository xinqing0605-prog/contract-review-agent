# ClauseGuard Web

合同审阅工作台前端。React 19 + TypeScript + Vite + Tailwind v4。

## 为什么重写

原来的 `index.html + app.js` 是原生 JS 单文件，工作流用 `setTimeout` 演动画，后端返回的
`text_length` 也没有正文可用，高亮无法实现。这次重写的目标不是"换个框架"，是把三件事做真：

1. **原文高亮**：直接用后端返回的 `start_offset / end_offset` 切片渲染，前后端共用一套坐标
2. **双向联动**：点原文 → 列表滚动 + 详情切换；点列表 → 原文滚动到该句
3. **真实链路**：时间线展示后端返回的 `trace`，前端不编造步骤

## 命令

```powershell
cd F:\contract-review-agent\web
npm install
npm run dev        # http://localhost:5173 ，/api 已代理到 127.0.0.1:8103
npx tsc --noEmit
npm test       # 偏移量计算的纯函数单测
npm run build
```

先起后端（项目根目录 `run_local.ps1`），再起前端。

## 结构

```
src/
  api/client.ts          类型化 fetch + ApiError + 后端未连接的可读提示
  hooks/useWorkspace.ts  状态机：连接 / 文档 / 正文 / 审阅 / 确认
  lib/offset.ts          偏移量 → 渲染片段的纯函数（有单测）
  components/
    SourceText          原文 + 高亮 + 滚动联动
    ClauseList          风险筛选 + 条款卡片
    ClauseDetail        原文证据 / 风险解释 / 建议 / 采纳驳回
    WorkflowTimeline    后端 trace 渲染，失败降级提示
    DocumentPanel       文档列表
    PasteDialog         粘贴合同（走 /api/documents/upload）
    MetricsBar          文档 / 条款 / 高风险 / 已确认 / 耗时
```

## 与后端的契约

| 接口 | 用途 |
| --- | --- |
| `GET /api/health` | 判断是否连得上，决定按钮可用性 |
| `GET /api/documents` | 列表 + 每份的条款 |
| `GET /api/documents/{id}/text` | 正文（按需加载，避免列表扛几百 KB） |
| `POST /api/documents/{id}/review` | 审阅，返回 `trace / model_meta / duration_ms` |
| `POST /api/clauses/{id}/approve` | 采纳或驳回，写审计 |
| `POST /api/documents/upload` | 粘贴导入 |

## 还没做（按优先级）

1. **SSE 流式**：现在 `review` 是一次性 JSON，时间线只能在返回后一次性渲染。
   改成 `text/event-stream` 后，每个步骤可以边跑边落，条款也能逐条出现。
2. **长文档虚拟滚动**：合同上千行时全量渲染 `mark` 会卡，需要按可视区切片。
3. **PDF 定位**：pdf.js 解析后要建立"文本框 → 字符偏移"的映射，这是真正的难点。
4. **成本看板**：`model_meta.usage` 已经有了，前端还没算钱。

## 约定

- 组件不直接 `fetch`，一律走 `api`
- 派生状态用 `useMemo`，不要在 render 里 filter 出新数组再当依赖
- 空态、错误态、加载态三件套必须有，不允许"看起来能用"其实没数据
