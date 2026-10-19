import type { Clause } from '../types'

export interface Segment {
  start: number
  end: number
  clause: Clause | null
}

/**
 * 把正文切成「普通文本 / 条款片段」交替的序列，供原文高亮渲染。
 *
 * 规则：
 * - 越界或零长度片段直接丢弃，避免渲染出空 mark
 * - 片段重叠时按起点排序后裁剪后一段的起点，保证 mark 不嵌套（嵌套在浏览器里选区行为很怪）
 * - 不修改输入数组
 */
export function buildSegments(text: string, clauses: Clause[]): Segment[] {
  if (text.length === 0) return []
  const ordered = clauses
    .filter(
      (clause) =>
        scopeOk(clause, text.length) && clause.start_offset >= 0 && clause.end_offset > clause.start_offset,
    )
    .sort((a, b) => a.start_offset - b.start_offset || b.end_offset - a.end_offset)

  const segments: Segment[] = []
  let cursor = 0

  for (const clause of ordered) {
    const start = Math.max(clause.start_offset, cursor)
    if (start >= clause.end_offset) continue
    if (start > cursor) {
      segments.push({ start: cursor, end: start, clause: null })
    }
    segments.push({ start, end: clause.end_offset, clause })
    cursor = clause.end_offset
  }

  if (cursor < text.length) {
    segments.push({ start: cursor, end: text.length, clause: null })
  }

  return segments
}

/** 命中位置所属的条款，找不到返回 null */
export function clauseAtOffset(clauses: Clause[], offset: number): Clause | null {
  for (const clause of clauses) {
    if (offset >= clause.start_offset && offset < clause.end_offset) return clause
  }
  return null
}

/** 两点之间是否包含 clause，用于「从原文反向联动到列表」 */
export function overlappingClauses(clauses: Clause[], start: number, end: number): Clause[] {
  return clauses.filter((clause) => clause.start_offset < end && start < clause.end_offset)
}

function scopeOk(clause: Clause, length: number): boolean {
  return clause.end_offset <= length && clause.start_offset < clause.end_offset
}
