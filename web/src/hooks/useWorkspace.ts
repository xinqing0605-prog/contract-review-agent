import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, errorMessage } from '../api/client'
import type { Clause, DocumentRecord, ModelMeta, RiskFilter, TraceStep } from '../types'
import { RISK_WEIGHT } from '../types'

export type Connection = 'booting' | 'online' | 'offline'

export interface Counts {
  total: number
  high: number
  medium: number
  low: number
  accepted: number
}

export interface AuditEvent {
  id: number
  action: string
  payload: Record<string, unknown>
  created_at: string
}

export interface Workspace {
  connection: Connection
  documents: DocumentRecord[]
  activeDocument: DocumentRecord | null
  text: string
  clauses: Clause[]
  visibleClauses: Clause[]
  activeClause: Clause | null
  activeClauseId: string | null
  filter: RiskFilter
  reviewing: boolean
  trace: TraceStep[]
  meta: ModelMeta | null
  durationMs: number | null
  modelError: string | null
  /** 本次审阅沿用了几条人工处置 */
  reviewKept: number
  error: string | null
  counts: Counts
  auditEvents: AuditEvent[] | null
  selectDocument: (id: string) => void
  selectClause: (id: string | null) => void
  setFilter: (filter: RiskFilter) => void
  runReview: () => Promise<void>
  decide: (accepted: boolean) => Promise<void>
  comment: (text: string) => Promise<void>
  upload: (name: string, text: string) => Promise<void>
  uploadFile: (file: File) => Promise<void>
  removeDocument: (id: string) => Promise<void>
  openAudit: () => Promise<void>
  closeAudit: () => void
  refresh: () => Promise<void>
  dismissError: () => void
}

const EMPTY_COUNTS: Counts = { total: 0, high: 0, medium: 0, low: 0, accepted: 0 }

export function useWorkspace(): Workspace {
  const [connection, setConnection] = useState<Connection>('booting')
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null)
  const [activeClauseId, setActiveClauseId] = useState<string | null>(null)
  const [filter, setFilter] = useState<RiskFilter>('all')
  const [reviewing, setReviewing] = useState(false)
  const [trace, setTrace] = useState<TraceStep[]>([])
  const [meta, setMeta] = useState<ModelMeta | null>(null)
  const [durationMs, setDurationMs] = useState<number | null>(null)
  const [modelError, setModelError] = useState<string | null>(null)
  const [reviewKept, setReviewKept] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [auditEvents, setAuditEvents] = useState<AuditEvent[] | null>(null)
  const textCache = useRef(new Map<string, string>())

  const activeDocument = useMemo(
    () => documents.find((item) => item.id === activeDocumentId) ?? null,
    [documents, activeDocumentId],
  )

  const clauses = useMemo(() => activeDocument?.clauses ?? [], [activeDocument])

  const visibleClauses = useMemo(() => {
    const list = filter === 'all' ? clauses : clauses.filter((clause) => clause.risk === filter)
    return [...list].sort(
      (a, b) => RISK_WEIGHT[a.risk] - RISK_WEIGHT[b.risk] || a.start_offset - b.start_offset,
    )
  }, [clauses, filter])

  const activeClause = useMemo(
    () => clauses.find((clause) => clause.id === activeClauseId) ?? null,
    [clauses, activeClauseId],
  )

  const counts = useMemo<Counts>(() => {
    if (clauses.length === 0) return EMPTY_COUNTS
    return clauses.reduce<Counts>(
      (acc, clause) => {
        acc.total += 1
        acc[clause.risk] += 1
        if (clause.accepted) acc.accepted += 1
        return acc
      },
      { total: 0, high: 0, medium: 0, low: 0, accepted: 0 },
    )
  }, [clauses])

  const loadDocuments = useCallback(async () => {
    try {
      const list = await api.documents()
      setDocuments(list)
      setConnection('online')
      setActiveDocumentId((current) => current ?? list[0]?.id ?? null)
      setActiveClauseId((current) => current ?? list[0]?.clauses?.[0]?.id ?? null)
      setError(null)
    } catch (cause) {
      setConnection('offline')
      setError(errorMessage(cause))
    }
  }, [])

  useEffect(() => {
    void loadDocuments()
  }, [loadDocuments])

  useEffect(() => {
    if (!activeDocument) {
      setText('')
      return
    }
    const cached = textCache.current.get(activeDocument.id)
    if (cached !== undefined) {
      setText(cached)
      return
    }
    let cancelled = false
    void api
      .text(activeDocument.id)
      .then((body) => {
        textCache.current.set(body.id, body.text)
        if (!cancelled) setText(body.text)
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setText('')
        setError(errorMessage(cause))
      })
    return () => {
      cancelled = true
    }
  }, [activeDocument])

  const selectDocument = useCallback(
    (id: string) => {
      const target = documents.find((item) => item.id === id)
      setActiveDocumentId(id)
      setActiveClauseId(target?.clauses?.[0]?.id ?? null)
      setTrace([])
      setMeta(null)
      setDurationMs(null)
      setModelError(null)
      setAuditEvents(null)
    },
    [documents],
  )

  const runReview = useCallback(async () => {
    if (!activeDocument) return
    setReviewing(true)
    setError(null)
    setModelError(null)
    setDurationMs(null)
    setTrace([{ step: '提交审阅请求', status: 'running', detail: activeDocument.name }])

    try {
      const result = await api.reviewStream(activeDocument.id, (step) => {
        setTrace((previous) => {
          // 第一条是前端占位的「提交审阅请求」，后端第一条真实步骤到达后要把它移除，
          // 否则它会一直停在 running 状态转圈
          const cleaned = previous.filter((item) => item.step !== '提交审阅请求')
          const index = cleaned.findIndex((item) => item.step === step.step)
          if (index < 0) return [...cleaned, step]
          const next = [...cleaned]
          next[index] = step
          return next
        })
      })
      setDocuments((current) =>
        current.map((item) => (item.id === result.document.id ? { ...result.document } : item)),
      )
      setMeta(result.model_meta)
      setModelError(result.model_error)
      setReviewKept(result.kept ?? 0)
      setDurationMs(result.duration_ms)
      setActiveClauseId(result.document.clauses?.[0]?.id ?? null)
    } catch (cause) {
      const message = errorMessage(cause)
      setError(message)
      setTrace((previous) => [...previous, { step: '审阅失败', status: 'error', detail: message }])
    } finally {
      setReviewing(false)
    }
  }, [activeDocument])

  const patchClause = useCallback((clause: Clause) => {
    setDocuments((current) =>
      current.map((document) =>
        document.id === clause.document_id
          ? {
              ...document,
              clauses: (document.clauses ?? []).map((item) =>
                item.id === clause.id ? clause : item,
              ),
            }
          : document,
      ),
    )
  }, [])

  const decide = useCallback(
    async (accepted: boolean) => {
      if (!activeClause) return
      try {
        const result = await api.approve(activeClause.id, accepted)
        patchClause(result.clause)
      } catch (cause) {
        setError(errorMessage(cause))
      }
    },
    [activeClause, patchClause],
  )

  const comment = useCallback(
    async (value: string) => {
      if (!activeClause) return
      try {
        const result = await api.comment(activeClause.id, value)
        patchClause(result.clause)
      } catch (cause) {
        setError(errorMessage(cause))
      }
    },
    [activeClause, patchClause],
  )

  const adopt = useCallback((created: DocumentRecord) => {
    textCache.current.delete(created.id)
    setDocuments((current) => [created, ...current])
    setActiveDocumentId(created.id)
    setActiveClauseId(created.clauses?.[0]?.id ?? null)
    setTrace([])
    setMeta(null)
    setDurationMs(null)
    setError(null)
    setAuditEvents(null)
  }, [])

  const upload = useCallback(
    async (name: string, value: string) => {
      const created = await api.upload(name, value)
      adopt(created)
    },
    [adopt],
  )

  const uploadFile = useCallback(
    async (file: File) => {
      try {
        const created = await api.uploadFile(file)
        adopt(created)
      } catch (cause) {
        setError(errorMessage(cause))
        throw cause
      }
    },
    [adopt],
  )

  const removeDocument = useCallback(
    async (id: string) => {
      try {
        await api.remove(id)
        textCache.current.delete(id)
        setDocuments((current) => {
          const next = current.filter((item) => item.id !== id)
          if (activeDocumentId === id) {
            setActiveDocumentId(next[0]?.id ?? null)
            setActiveClauseId(next[0]?.clauses?.[0]?.id ?? null)
          }
          return next
        })
      } catch (cause) {
        setError(errorMessage(cause))
      }
    },
    [activeDocumentId],
  )

  const openAudit = useCallback(async () => {
    if (!activeDocument) return
    try {
      setAuditEvents(await api.audit(activeDocument.id))
    } catch (cause) {
      setError(errorMessage(cause))
    }
  }, [activeDocument])

  return {
    connection,
    documents,
    activeDocument,
    text,
    clauses,
    visibleClauses,
    activeClause,
    activeClauseId,
    filter,
    reviewing,
    trace,
    meta,
    durationMs,
    modelError,
    reviewKept,
    error,
    counts,
    auditEvents,
    selectDocument,
    selectClause: setActiveClauseId,
    setFilter,
    runReview,
    decide,
    comment,
    upload,
    uploadFile,
    removeDocument,
    openAudit,
    closeAudit: () => setAuditEvents(null),
    refresh: loadDocuments,
    dismissError: () => setError(null),
  }
}
