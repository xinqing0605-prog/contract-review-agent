import { describe, expect, it } from 'vitest'
import { buildSegments, clauseAtOffset, overlappingClauses } from './offset'
import type { Clause } from '../types'

function makeClause(overrides: Partial<Clause>): Clause {
  return {
    id: 'c1',
    document_id: 'd1',
    title: '付款与验收',
    risk: 'high',
    excerpt: '',
    original: '',
    reason: '',
    recommend: '',
    start_offset: 0,
    end_offset: 1,
    accepted: 0,
    comment: '',
    ...overrides,
  }
}

describe('buildSegments', () => {
  it('没有条款时返回单个普通片段', () => {
    expect(buildSegments('abc', [])).toEqual([{ start: 0, end: 3, clause: null }])
  })

  it('条款落在中间时切成三段', () => {
    const clause = makeClause({ start_offset: 1, end_offset: 3 })
    expect(buildSegments('abcdef', [clause])).toEqual([
      { start: 0, end: 1, clause: null },
      { start: 1, end: 3, clause },
      { start: 3, end: 6, clause: null },
    ])
  })

  it('重叠片段的起点被裁剪，不产生嵌套', () => {
    const first = makeClause({ id: 'a', start_offset: 0, end_offset: 4 })
    const second = makeClause({ id: 'b', start_offset: 2, end_offset: 6 })
    const segments = buildSegments('0123456789', [first, second])
    const covered = segments.filter((s) => s.clause).map((s) => [s.start, s.end])
    expect(covered).toEqual([
      [0, 4],
      [4, 6],
    ])
  })

  it('完全被包含的片段会被丢弃', () => {
    const outer = makeClause({ id: 'outer', start_offset: 0, end_offset: 6 })
    const inner = makeClause({ id: 'inner', start_offset: 1, end_offset: 3 })
    const segments = buildSegments('0123456789', [outer, inner])
    expect(segments.filter((s) => s.clause)).toHaveLength(1)
  })

  it('越界片段不参与渲染', () => {
    const clause = makeClause({ start_offset: 8, end_offset: 99 })
    expect(buildSegments('abc', [clause])).toEqual([{ start: 0, end: 3, clause: null }])
  })

  it('空正文返回空数组', () => {
    expect(buildSegments('', [makeClause({})])).toEqual([])
  })
})

describe('clauseAtOffset', () => {
  const clause = makeClause({ start_offset: 5, end_offset: 9 })

  it('命中区间内返回条款', () => {
    expect(clauseAtOffset([clause], 5)?.id).toBe('c1')
    expect(clauseAtOffset([clause], 8)?.id).toBe('c1')
  })

  it('区间外返回 null', () => {
    expect(clauseAtOffset([clause], 4)).toBeNull()
    expect(clauseAtOffset([clause], 9)).toBeNull()
  })
})

describe('overlappingClauses', () => {
  it('按区间相交而不是包含判断', () => {
    const a = makeClause({ id: 'a', start_offset: 0, end_offset: 5 })
    const b = makeClause({ id: 'b', start_offset: 10, end_offset: 15 })
    expect(overlappingClauses([a, b], 4, 11).map((c) => c.id)).toEqual(['a', 'b'])
  })
})
