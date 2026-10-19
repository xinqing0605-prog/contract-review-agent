import type { AuditEvent } from '../hooks/useWorkspace'
import { CloseButton } from './ui'

/** 后端存的是 UTC（SQLite CURRENT_TIMESTAMP），展示要转成本地时间 */
function localTime(value: string): string {
  if (!value) return ''
  const iso = value.includes('T') ? value : `${value.replace(' ', 'T')}Z`
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

const LABEL: Record<string, string> = {
  upload: '导入合同',
  review: '执行审阅',
  approve_clause: '采纳建议',
  reject_clause: '驳回建议',
  comment_clause: '保存批注',
  delete: '删除合同',
}

const TONE: Record<string, string> = {
  upload: 'text-slate-600',
  review: 'text-slate-900',
  approve_clause: 'text-emerald-700',
  reject_clause: 'text-amber-700',
  comment_clause: 'text-sky-700',
  delete: 'text-red-700',
}

function summary(event: AuditEvent): string {
  const payload = event.payload ?? {}
  if (event.action === 'upload') return `${payload.chars ?? '?'} 字符 · ${payload.source ?? 'text'}`
  if (event.action === 'review') {
    return `${payload.clauses ?? '?'} 条条款 · ${payload.high ?? '?'} 条高风险 · ${payload.model ?? '规则'}`
  }
  if (typeof payload.title === 'string') return payload.title
  if (typeof payload.clause_id === 'string') return payload.clause_id
  return ''
}

export function AuditPanel({
  events,
  documentName,
  onClose,
}: {
  events: AuditEvent[] | null
  documentName: string
  onClose: () => void
}) {
  if (events === null) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-16"
      role="dialog"
      aria-modal="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">审计日志</h2>
            <p className="mt-0.5 text-[11px] text-slate-500">{documentName}</p>
          </div>
          <CloseButton onClick={onClose} />
        </div>

        {events.length === 0 ? (
          <p className="py-8 text-center text-xs text-slate-400">还没有操作记录</p>
        ) : (
          <ol className="scroll-thin mt-3 max-h-[60vh] space-y-2 overflow-y-auto">
            {events.map((event) => (
              <li key={event.id} className="rounded-lg border border-slate-100 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className={`text-xs font-medium ${TONE[event.action] ?? 'text-slate-700'}`}>
                    {LABEL[event.action] ?? event.action}
                  </span>
                  <span className="text-[10px] tabular-nums text-slate-400">{localTime(event.created_at)}</span>
                </div>
                <p className="mt-0.5 truncate text-[11px] text-slate-500">{summary(event)}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  )
}
