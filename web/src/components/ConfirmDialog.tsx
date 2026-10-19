import { useEffect } from 'react'

interface Props {
  open: boolean
  title: string
  message: string
  confirmText?: string
  tone?: 'danger' | 'default'
  onCancel: () => void
  onConfirm: () => void
}

/** 通用确认框：替代浏览器原生 confirm，风格与项目其它弹窗一致 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmText = '确认',
  tone = 'danger',
  onCancel,
  onConfirm,
}: Props) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl">
        <div className="flex items-start gap-3">
          <span
            className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm ${
              tone === 'danger' ? 'bg-red-50 text-red-600' : 'bg-slate-100 text-slate-600'
            }`}
            aria-hidden
          >
            !
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
            <p className="mt-1 text-[11px] leading-5 text-slate-500">{message}</p>
          </div>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            type="button"
            autoFocus
            onClick={onConfirm}
            className={`rounded-md px-3 py-1.5 text-xs font-medium text-white ${
              tone === 'danger'
                ? 'bg-red-600 hover:bg-red-500'
                : 'bg-slate-900 hover:bg-slate-800'
            }`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
