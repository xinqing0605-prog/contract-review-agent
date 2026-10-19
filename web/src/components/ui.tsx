import type { ReactNode } from 'react'
import type { Risk } from '../types'
import { RISK_LABEL } from '../types'

const TONE: Record<Risk, string> = {
  high: 'border-red-200 bg-red-50 text-red-700',
  medium: 'border-amber-200 bg-amber-50 text-amber-700',
  low: 'border-teal-200 bg-teal-50 text-teal-700',
}

const DOT: Record<Risk, string> = {
  high: 'bg-red-500',
  medium: 'bg-amber-500',
  low: 'bg-teal-500',
}

export function RiskBadge({ risk, compact = false }: { risk: Risk; compact?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${TONE[risk]}`}
    >
      <i className={`h-1.5 w-1.5 rounded-full ${DOT[risk]}`} aria-hidden />
      {compact ? RISK_LABEL[risk].replace('风险', '') : RISK_LABEL[risk]}
    </span>
  )
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = '',
}: {
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={`flex min-h-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}
    >
      <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-slate-900">{title}</h2>
          {subtitle ? <p className="mt-0.5 truncate text-xs text-slate-500">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
      </header>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">{children}</div>
    </section>
  )
}

export function Spinner({ className = 'h-3.5 w-3.5' }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" className="opacity-25" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        className="opacity-90"
      />
    </svg>
  )
}

export function CloseButton({ onClick, label = '关闭' }: { onClick: () => void; label?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="-mr-1 -mt-1 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
        <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    </button>
  )
}

/** 密码/密钥的显示隐藏开关 */
export function EyeButton({ shown, onToggle }: { shown: boolean; onToggle: () => void }) {
  const label = shown ? '隐藏' : '显示'
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={label}
      title={label}
      className="rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
        {shown ? (
          <>
            <path
              d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
            <circle cx="12" cy="12" r="2.6" stroke="currentColor" strokeWidth="1.8" />
          </>
        ) : (
          <>
            <path
              d="M2 12s3.6-6 10-6c1 0 1.9.15 2.7.4"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
            <path
              d="M22 12s-3.6 6-10 6c-1.2 0-2.3-.2-3.3-.6"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
            <path d="M4 4l16 16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </>
        )}
      </svg>
    </button>
  )
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="flex h-full min-h-32 flex-col items-center justify-center gap-2 px-6 py-8 text-center">
      <p className="text-sm font-medium text-slate-600">{title}</p>
      {hint ? <p className="max-w-xs text-xs leading-5 text-slate-400">{hint}</p> : null}
      {action}
    </div>
  )
}
