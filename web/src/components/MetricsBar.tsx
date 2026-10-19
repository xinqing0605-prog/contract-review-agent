import type { Counts } from '../hooks/useWorkspace'

interface Props {
  counts: Counts
  documentCount: number
  durationMs: number | null
  model: string | null
}

export function MetricsBar({ counts, documentCount, durationMs, model }: Props) {
  const items: { label: string; value: string | number; note: string; tone?: string }[] = [
    { label: '文档', value: documentCount, note: '待审阅 / 已审阅' },
    { label: '识别条款', value: counts.total, note: '按句子定位' },
    { label: '高风险', value: counts.high, note: '建议优先处理', tone: 'text-red-600' },
    { label: '已确认', value: counts.accepted, note: `共 ${counts.total} 条待定`, tone: 'text-emerald-600' },
    {
      label: '单份耗时',
      value: durationMs === null ? '—' : `${(durationMs / 1000).toFixed(1)}s`,
      note: durationMs === null ? '运行审阅后统计' : (model ?? '规则模式'),
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {items.map((item) => (
        <div key={item.label} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
          <p className="text-[10px] text-slate-400">{item.label}</p>
          <p className={`mt-0.5 text-lg font-semibold tabular-nums ${item.tone ?? 'text-slate-900'}`}>
            {item.value}
          </p>
          <p className="truncate text-[10px] text-slate-400">{item.note}</p>
        </div>
      ))}
    </div>
  )
}
