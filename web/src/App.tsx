import { useCallback, useEffect, useState } from 'react'
import { api, type User } from './api/client'
import { AuditPanel } from './components/AuditPanel'
import { AuthScreen } from './components/AuthScreen'
import { ClauseDetail } from './components/ClauseDetail'
import { ClauseList } from './components/ClauseList'
import { DocumentPanel } from './components/DocumentPanel'
import { MetricsBar } from './components/MetricsBar'
import { ModelSettings } from './components/ModelSettings'
import { PasteDialog } from './components/PasteDialog'
import { SourceText } from './components/SourceText'
import { UsagePanel } from './components/UsagePanel'
import { WorkflowTimeline } from './components/WorkflowTimeline'
import { EmptyState, Panel, Spinner } from './components/ui'
import { useSession } from './hooks/useSession'
import { useWorkspace } from './hooks/useWorkspace'

const CONNECTION: Record<string, { label: string; tone: string }> = {
  booting: { label: '服务连接中', tone: 'bg-slate-300' },
  online: { label: '服务在线', tone: 'bg-emerald-500' },
  offline: { label: '服务离线', tone: 'bg-red-500' },
}

export default function App() {
  const session = useSession()

  if (session.status === 'booting') {
    return (
      <div className="flex min-h-screen items-center justify-center text-xs text-slate-400">
        <Spinner /> <span className="ml-2">加载中…</span>
      </div>
    )
  }

  if (session.status !== 'authed' || !session.user) {
    return (
      <AuthScreen
        error={session.error}
        onLogin={session.login}
        onRegister={session.register}
        onDismissError={session.dismissError}
      />
    )
  }

  return <WorkspaceShell user={session.user} onLogout={() => void session.logout()} />
}

function WorkspaceShell({ user, onLogout }: { user: User; onLogout: () => void }) {
  const workspace = useWorkspace()
  const [composing, setComposing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [usageOpen, setUsageOpen] = useState(false)

  const [activeModel, setActiveModel] = useState<string | null>(null)

  const loadActiveModel = useCallback(async () => {
    try {
      const body = await api.services.list()
      for (const service of body.services) {
        for (const model of service.models) {
          if (model.is_active) {
            setActiveModel(`${service.name} · ${model.name}`)
            return
          }
        }
      }
      setActiveModel(null)
    } catch {
      setActiveModel(null)
    }
  }, [])

  useEffect(() => {
    void loadActiveModel()
  }, [loadActiveModel])

  const connection = CONNECTION[workspace.connection] ?? CONNECTION.booting
  const canReview =
    workspace.connection === 'online' && workspace.activeDocument !== null && !workspace.reviewing

  async function handleCompose(name: string, text: string) {
    setUploading(true)
    try {
      await workspace.upload(name, text)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col xl:h-screen xl:min-h-0 xl:overflow-hidden">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/85 backdrop-blur">
        <div className="mx-auto flex w-full max-w-[1600px] items-center gap-3 px-4 py-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-[11px] font-bold text-white">
            CG
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold leading-tight text-slate-900">ClauseGuard</h1>
            <p className="truncate text-[10px] text-slate-500">
              合同审阅工作台 · 条款定位 / 风险分级 / 人工确认
            </p>
          </div>

          <span className="ml-2 inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-2 py-0.5 text-[10px] text-slate-500">
            <i className={`h-1.5 w-1.5 rounded-full ${connection.tone}`} aria-hidden />
            {connection.label}
          </span>

          <span
            title="当前审阅使用的模型"
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-700"
          >
            <i className="h-1.5 w-1.5 rounded-full bg-slate-900" aria-hidden />
            {activeModel ?? '未配置模型'}
          </span>

          <div className="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => void workspace.refresh()}
              className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              刷新
            </button>
            <button
              type="button"
              onClick={() => void workspace.openAudit()}
              disabled={!workspace.activeDocument}
              className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              审计
            </button>
            <button
              type="button"
              onClick={() => setUsageOpen(true)}
              className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              用量
            </button>

            <div className="relative">
              <button
                type="button"
                onClick={() => setExportOpen((value) => !value)}
                disabled={!workspace.activeDocument || workspace.clauses.length === 0}
                className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                导出报告
              </button>
              {exportOpen ? (
                <div className="absolute right-0 z-40 mt-1 w-32 overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg">
                  {(['docx', 'md'] as const).map((format) => (
                    <button
                      key={format}
                      type="button"
                      onClick={() => {
                        if (!workspace.activeDocument) return
                        window.open(api.exportUrl(workspace.activeDocument.id, format), '_blank')
                        setExportOpen(false)
                      }}
                      className="block w-full px-3 py-2 text-left text-xs text-slate-600 hover:bg-slate-50"
                    >
                      {format === 'docx' ? 'Word (.docx)' : 'Markdown (.md)'}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>

            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              模型设置
            </button>

            <button
              type="button"
              onClick={() => void workspace.runReview()}
              disabled={!canReview}
              className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {workspace.reviewing ? <Spinner className="h-3 w-3" /> : null}
              {workspace.reviewing ? '审阅中' : '运行审阅'}
            </button>

            <span className="mx-1 h-5 w-px bg-slate-200" aria-hidden />
            <span
              className="max-w-[140px] truncate text-[11px] text-slate-500"
              title={user.email ?? user.username ?? ''}
            >
              {user.email ?? user.username ?? '未命名'}
            </span>
            <button
              type="button"
              onClick={onLogout}
              className="rounded-md px-2 py-1.5 text-[11px] text-slate-500 hover:bg-slate-100"
            >
              退出
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-3 px-4 py-3 xl:min-h-0 xl:overflow-hidden">
        <div className="shrink-0">
        <MetricsBar
          counts={workspace.counts}
          documentCount={workspace.documents.length}
          durationMs={workspace.durationMs}
          model={workspace.meta?.model ?? null}
        />
        </div>

        {workspace.error ? (
          <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
            <p className="flex-1 text-xs leading-5 text-red-700">{workspace.error}</p>
            <button
              type="button"
              onClick={() => void workspace.refresh()}
              className="shrink-0 rounded-md border border-red-300 px-2 py-1 text-[11px] text-red-700 hover:bg-red-100"
            >
              重试
            </button>
            <button
              type="button"
              onClick={workspace.dismissError}
              className="shrink-0 text-[11px] text-red-500 hover:underline"
            >
              关闭
            </button>
          </div>
        ) : null}

        <div className="grid min-h-0 flex-1 gap-3 xl:grid-cols-[250px_minmax(0,1fr)_350px]">
          <Panel title="文档" subtitle={`${workspace.documents.length} 份`} className="min-h-0 xl:flex-1">
            <DocumentPanel
              documents={workspace.documents}
              activeId={workspace.activeDocument?.id ?? null}
              onSelect={workspace.selectDocument}
              onCompose={() => setComposing(true)}
              onUploadFile={(file) => void workspace.uploadFile(file)}
              onRemove={(id) => void workspace.removeDocument(id)}
            />
          </Panel>

          <div className="flex min-h-0 min-w-0 flex-col gap-3 [&>section]:min-h-0 [&>section]:flex-1">
            <Panel
              title={workspace.activeDocument?.name ?? '合同原文'}
              subtitle={
                workspace.text
                  ? `${workspace.text.length} 字符 · ID ${workspace.activeDocument?.id ?? '-'} · 点击高亮可联动`
                  : workspace.activeDocument
                    ? '加载中…'
                    : '尚未选择合同'
              }
            >
              <SourceText
                text={workspace.text}
                clauses={workspace.clauses}
                activeClauseId={workspace.activeClauseId}
                onSelect={workspace.selectClause}
              />
            </Panel>

            <Panel
              title="识别条款"
              subtitle={
                workspace.clauses.length > 0
                  ? `${workspace.clauses.length} 条 · 按句子定位${
                      workspace.reviewKept > 0 ? ` · 沿用 ${workspace.reviewKept} 条处置` : ''
                    }`
                  : '尚未审阅'
              }
            >
              <ClauseList
                clauses={workspace.clauses}
                visible={workspace.visibleClauses}
                activeId={workspace.activeClauseId}
                filter={workspace.filter}
                onFilter={workspace.setFilter}
                onSelect={workspace.selectClause}
              />
            </Panel>
          </div>

          <div className="flex min-h-0 min-w-0 flex-col gap-3 [&>section]:min-h-0 [&>section]:flex-1">
            <Panel title="审阅链路" subtitle="后端真实执行记录">
              <WorkflowTimeline
                steps={workspace.trace}
                reviewing={workspace.reviewing}
                mode={workspace.meta ? 'deepseek' : workspace.trace.length > 0 ? 'demo' : null}
                durationMs={workspace.durationMs}
                modelError={workspace.modelError}
                hint={
                  workspace.clauses.length > 0
                    ? '条款和原文高亮来自数据库里上次审阅的结果。点「运行审阅」重新执行，会看到逐步推送的链路。'
                    : '点「运行审阅」后，这里会逐步显示后端推送的每一步。'
                }
              />
            </Panel>

            <Panel title="条款详情" subtitle="原文证据与处置">
              {workspace.activeClause ? (
                <ClauseDetail
                  clause={workspace.activeClause}
                  onDecide={(accepted) => void workspace.decide(accepted)}
                  onReject={(reason) => void workspace.reject(reason)}
                  onExecute={() => void workspace.execute()}
                  onComment={(value) => void workspace.comment(value)}
                />
              ) : (
                <EmptyState
                  title="选择一条条款"
                  hint="点击原文高亮或中间的条款卡片，查看风险解释与修改建议。"
                />
              )}
            </Panel>
          </div>
        </div>

        <footer className="pb-2 text-[10px] text-slate-400">
          每个账号的合同与模型配置互相隔离；Key 加密存储且不回传浏览器。评测集在
          <code className="mx-1">eval/</code>，检测规则在
          <code className="mx-1">backend/detector.py</code>。
        </footer>
      </main>

      <PasteDialog
        open={composing}
        busy={uploading}
        onClose={() => setComposing(false)}
        onSubmit={handleCompose}
      />
      <ModelSettings
        open={settingsOpen}
        onClose={() => {
          setSettingsOpen(false)
          void loadActiveModel()
        }}
      />
      <AuditPanel
        events={workspace.auditEvents}
        documentName={workspace.activeDocument?.name ?? ''}
        onClose={workspace.closeAudit}
      />
      <UsagePanel open={usageOpen} onClose={() => setUsageOpen(false)} />
    </div>
  )
}
