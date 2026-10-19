import { useEffect, useState, type ReactNode } from 'react'
import type { Clause } from '../types'
import { EmptyState, RiskBadge } from './ui'

interface Props {
  clause: Clause | null
  onDecide: (accepted: boolean) => void
  onComment: (comment: string) => void
}

export function ClauseDetail({ clause, onDecide, onComment }: Props) {
  const [draft, setDraft] = useState('')

  useEffect(() => {
    setDraft(clause?.comment ?? '')
  }, [clause?.id, clause?.comment])

  if (!clause) {
    return <EmptyState title="选择一条条款" hint="点击原文里的高亮，或点击中间的条款卡片。" />
  }

  const dirty = draft.trim() !== (clause.comment ?? '')

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-2 px-4 pt-3">
        <div>
          <p className="text-[10px] font-semibold tracking-widest text-slate-400">
            {clause.risk === 'high' ? 'HIGH RISK' : 'CLAUSE EVIDENCE'}
          </p>
          <h3 className="mt-0.5 text-sm font-semibold text-slate-900">{clause.title}</h3>
        </div>
        <RiskBadge risk={clause.risk} />
      </div>

      <div className="mt-2 space-y-3 px-4 pb-2">
        <Block label="原文片段">
          <p className="border-l-2 border-slate-300 pl-2.5 text-xs leading-6 text-slate-700">
            {clause.original}
          </p>
          <p className="mt-1 text-[10px] text-slate-400">
            第 {clause.start_offset}–{clause.end_offset} 字
          </p>
        </Block>

        <Block label="风险解释">
          <p className="text-xs leading-6 text-slate-600">{clause.reason}</p>
        </Block>

        <Block label="修改建议">
          <p className="rounded-md bg-slate-50 p-2.5 text-xs leading-6 text-slate-700">
            {clause.recommend}
          </p>
        </Block>

        <Block label="批注（会写进报告和审计）">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={2}
            placeholder="例如：已与供应商确认改为 60 日"
            className="w-full resize-none rounded-md border border-slate-200 p-2 text-xs leading-5 outline-none focus:border-slate-400"
          />
          <div className="mt-1 flex items-center gap-2">
            <button
              type="button"
              disabled={!dirty}
              onClick={() => onComment(draft.trim())}
              className="rounded-md border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              保存批注
            </button>
            {dirty ? <span className="text-[10px] text-amber-600">未保存</span> : null}
          </div>
        </Block>
      </div>

      <div className="mt-auto flex items-center gap-2 border-t border-slate-100 px-4 py-2.5">
        {clause.accepted ? (
          <>
            <span className="text-xs font-medium text-emerald-600">已采纳</span>
            <button
              type="button"
              onClick={() => onDecide(false)}
              className="ml-auto rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              撤销
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={() => onDecide(true)}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
            >
              采纳建议
            </button>
            <button
              type="button"
              onClick={() => onDecide(false)}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              标记驳回
            </button>
            <span className="ml-auto text-[10px] text-slate-400">写入审计记录</span>
          </>
        )}
      </div>
    </div>
  )
}

function Block({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-[10px] font-semibold tracking-wide text-slate-400">{label}</p>
      {children}
    </div>
  )
}
