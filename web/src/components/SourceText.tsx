import { useEffect, useMemo, useRef } from 'react'
import type { Clause } from '../types'
import { RISK_LABEL } from '../types'
import { buildSegments } from '../lib/offset'
import { EmptyState } from './ui'

interface Props {
  text: string
  clauses: Clause[]
  activeClauseId: string | null
  onSelect: (clauseId: string) => void
}

/**
 * 原文区：按条款偏移量渲染高亮，并与右侧详情双向联动。
 *
 * 这是整个前端最关键的一块——条款的 start_offset / end_offset 直接决定
 * 高亮能不能和原文对齐。偏移量一旦漂移，用户看到的证据就是错的。
 */
export function SourceText({ text, clauses, activeClauseId, onSelect }: Props) {
  const segments = useMemo(() => buildSegments(text, clauses), [text, clauses])
  const marks = useRef(new Map<string, HTMLElement>())

  useEffect(() => {
    if (!activeClauseId) return
    marks.current.get(activeClauseId)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [activeClauseId])

  if (!text) {
    return <EmptyState title="还没有正文" hint="选择左侧文档，或粘贴一份合同文本开始审阅。" />
  }

  return (
    <div className="whitespace-pre-wrap break-words px-5 py-4 text-[15px] leading-8 text-slate-800">
      {segments.map((segment) => {
        const clause = segment.clause
        if (!clause) {
          return <span key={`plain-${segment.start}`}>{text.slice(segment.start, segment.end)}</span>
        }
        return (
          <mark
            key={`mark-${clause.id}-${segment.start}`}
            ref={(node) => {
              if (node) marks.current.set(clause.id, node)
              else marks.current.delete(clause.id)
            }}
            data-risk={clause.risk}
            data-active={clause.id === activeClauseId}
            className="clause-mark"
            title={`${clause.title} · ${RISK_LABEL[clause.risk]}`}
            onClick={() => onSelect(clause.id)}
          >
            {text.slice(segment.start, segment.end)}
          </mark>
        )
      })}
    </div>
  )
}
