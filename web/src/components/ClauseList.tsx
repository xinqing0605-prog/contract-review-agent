import { useEffect, useRef } from 'react'
import type { Clause, RiskFilter } from '../types'
import { RISK_LABEL } from '../types'
import { EmptyState, RiskBadge } from './ui'

interface Props {
  clauses: Clause[]
  visible: Clause[]
  activeId: string | null
  filter: RiskFilter
  onFilter: (filter: RiskFilter) => void
  onSelect: (clauseId: string) => void
}

const FILTERS: { value: RiskFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'high', label: '高' },
  { value: 'medium', label: '中' },
  { value: 'low', label: '低' },
]

export function ClauseList({ clauses, visible, activeId, filter, onFilter, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!activeId) return
    const node = containerRef.current?.querySelector<HTMLElement>(`[data-clause-id="${activeId}"]`)
    node?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeId])

  const countOf = (value: RiskFilter) =>
    value === 'all' ? clauses.length : clauses.filter((clause) => clause.risk === value).length

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex items-center gap-1 border-b border-slate-100 px-3 py-2">
        {FILTERS.map((item) => {
          const active = filter === item.value
          return (
            <button
              key={item.value}
              type="button"
              onClick={() => onFilter(item.value)}
              aria-pressed={active}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                active ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {item.label}
              <span className={`ml-1 ${active ? 'text-white/70' : 'text-slate-400'}`}>
                {countOf(item.value)}
              </span>
            </button>
          )
        })}
      </div>

      {clauses.length === 0 ? (
        <EmptyState title="还没有条款" hint="点击右上角「运行审阅」，条款会按风险排序列在这里。" />
      ) : visible.length === 0 ? (
        <EmptyState title="没有匹配的条款" hint={`当前筛选：${RISK_LABEL[filter as Exclude<RiskFilter, 'all'>]}`} />
      ) : (
        <div ref={containerRef} className="p-2">
          <ul className="space-y-1.5">
            {visible.map((clause) => {
              const active = clause.id === activeId
              return (
                <li key={clause.id}>
                  <button
                    type="button"
                    data-clause-id={clause.id}
                    onClick={() => onSelect(clause.id)}
                    className={`w-full rounded-lg border p-2.5 text-left transition ${
                      active
                        ? 'border-slate-900 bg-slate-50 shadow-sm'
                        : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-slate-800">{clause.title}</span>
                      <span className="flex shrink-0 items-center gap-1">
                        {clause.status !== 'pending' ? (
                          <span
                            className={`text-[10px] font-medium ${
                              clause.status === 'executed'
                                ? 'text-emerald-600'
                                : clause.status === 'approved'
                                  ? 'text-sky-600'
                                  : 'text-amber-600'
                            }`}
                          >
                            {clause.status === 'executed'
                              ? '已执行'
                              : clause.status === 'approved'
                                ? '已通过'
                                : '已驳回'}
                          </span>
                        ) : null}
                        <RiskBadge risk={clause.risk} compact />
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{clause.excerpt}</p>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
      <div className="mt-auto border-t border-slate-100 px-3 py-1.5 text-[10px] text-slate-400">
        高风险优先 · 同风险按原文位置排序
      </div>
    </div>
  )
}
