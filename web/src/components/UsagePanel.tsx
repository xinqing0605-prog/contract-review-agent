import { useEffect, useState } from 'react'
import { api, errorMessage, type LlmUsage } from '../api/client'
import { CloseButton, Spinner } from './ui'

function localTime(value: string): string {
  if (!value) return ''
  const iso = value.includes('T') ? value : `${value.replace(' ', 'T')}Z`
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function compact(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return String(value)
}

const RANGE_OPTIONS = [7, 14, 30] as const

export function UsagePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [days, setDays] = useState<number>(7)
  const [usage, setUsage] = useState<LlmUsage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError('')
    api.metrics
      .llm(days)
      .then((body) => {
        if (!cancelled) setUsage(body)
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, days])

  if (!open) return null

  const totals = usage?.totals
  const cards = [
    { label: '调用次数', value: totals ? compact(totals.calls) : '—' },
    { label: 'Token 合计', value: totals ? compact(totals.total_tokens) : '—' },
    { label: '平均耗时', value: totals ? `${Math.round(totals.avg_duration_ms)} ms` : '—' },
    {
      label: '失败',
      value: totals ? `${totals.failed}` : '—',
      tone: totals && totals.failed > 0 ? 'text-red-600' : 'text-slate-900',
    },
  ]

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-16"
      role="dialog"
      aria-modal="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-lg rounded-xl bg-white p-5 shadow-xl">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">模型调用用量</h2>
            <p className="mt-0.5 text-[11px] text-slate-500">
              记录每次调用与连接检测的 token、耗时与失败情况，仅统计当前账号
            </p>
          </div>
          <CloseButton onClick={onClose} />
        </div>

        <div className="mt-3 flex items-center gap-1.5">
          {RANGE_OPTIONS.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setDays(value)}
              className={`rounded-md border px-2 py-1 text-[11px] ${
                days === value
                  ? 'border-slate-900 bg-slate-900 text-white'
                  : 'border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              近 {value} 天
            </button>
          ))}
          {loading ? (
            <span className="ml-1 inline-flex items-center gap-1 text-[11px] text-slate-400">
              <Spinner className="h-3 w-3" /> 加载中
            </span>
          ) : null}
        </div>

        {error ? <p className="mt-3 text-xs text-red-600">{error}</p> : null}

        <div className="mt-3 grid grid-cols-4 gap-2">
          {cards.map((card) => (
            <div key={card.label} className="rounded-lg border border-slate-100 px-2 py-2">
              <p className="text-[10px] text-slate-500">{card.label}</p>
              <p className={`mt-0.5 text-sm font-semibold tabular-nums ${card.tone ?? 'text-slate-900'}`}>
                {card.value}
              </p>
            </div>
          ))}
        </div>

        {usage && usage.by_model.length > 0 ? (
          <div className="mt-4">
            <h3 className="text-[11px] font-medium text-slate-700">按模型</h3>
            <table className="mt-1.5 w-full text-[11px]">
              <thead className="text-slate-400">
                <tr>
                  <th className="py-1 text-left font-normal">模型</th>
                  <th className="py-1 text-right font-normal">次数</th>
                  <th className="py-1 text-right font-normal">Token</th>
                  <th className="py-1 text-right font-normal">平均耗时</th>
                  <th className="py-1 text-right font-normal">失败</th>
                </tr>
              </thead>
              <tbody>
                {usage.by_model.map((row) => (
                  <tr key={row.model} className="border-t border-slate-100">
                    <td className="max-w-[180px] truncate py-1 text-slate-700" title={row.model}>
                      {row.model}
                    </td>
                    <td className="py-1 text-right tabular-nums text-slate-600">{row.calls}</td>
                    <td className="py-1 text-right tabular-nums text-slate-600">
                      {compact(row.total_tokens)}
                    </td>
                    <td className="py-1 text-right tabular-nums text-slate-600">
                      {Math.round(row.avg_duration_ms)} ms
                    </td>
                    <td
                      className={`py-1 text-right tabular-nums ${
                        row.failed > 0 ? 'text-red-600' : 'text-slate-400'
                      }`}
                    >
                      {row.failed}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {usage && usage.recent.length > 0 ? (
          <div className="mt-4">
            <h3 className="text-[11px] font-medium text-slate-700">最近调用</h3>
            <ol className="scroll-thin mt-1.5 max-h-[30vh] space-y-1 overflow-y-auto">
              {usage.recent.map((item) => (
                <li
                  key={item.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-slate-100 px-2 py-1"
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    <i
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        item.ok ? 'bg-emerald-500' : 'bg-red-500'
                      }`}
                      aria-hidden
                    />
                    <span className="truncate text-[11px] text-slate-600">
                      {item.purpose_label} · {item.model || '未记录'}
                      {item.ok ? '' : ` · ${item.error.slice(0, 40)}`}
                    </span>
                  </span>
                  <span className="shrink-0 text-[10px] tabular-nums text-slate-400">
                    {compact(item.total_tokens)} tok · {Math.round(item.duration_ms)} ms ·{' '}
                    {localTime(item.created_at)}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        {usage && usage.totals.calls === 0 ? (
          <p className="mt-4 rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">
            这段时间还没有模型调用。配置模型并运行一次审阅后，这里会出现记录。
          </p>
        ) : null}
      </div>
    </div>
  )
}
