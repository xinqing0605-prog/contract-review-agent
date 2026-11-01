import { useEffect, useRef, useState } from 'react'
import { Spinner } from './ui'

interface Props {
  canAudit: boolean
  canExport: boolean
  canReview: boolean
  reviewing: boolean
  onRefresh: () => void
  onAudit: () => void
  onUsage: () => void
  onRecall: () => void
  onSettings: () => void
  onReview: () => void
  onExport: (format: 'docx' | 'md') => void
}

const BUTTON =
  'whitespace-nowrap rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40'

/**
 * 顶栏操作区：宽屏全部平铺，窄屏把次要操作收进「更多」。
 * 目标是任何宽度下都只有一行，按钮里的文字不折行。
 */
export function HeaderActions({
  canAudit,
  canExport,
  canReview,
  reviewing,
  onRefresh,
  onAudit,
  onUsage,
  onRecall,
  onSettings,
  onReview,
  onExport,
}: Props) {
  const [moreOpen, setMoreOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const moreRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!moreOpen) return
    function handle(event: MouseEvent) {
      if (moreRef.current && !moreRef.current.contains(event.target as Node)) {
        setMoreOpen(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [moreOpen])

  const secondary = [
    { key: 'audit', label: '审计', onClick: onAudit, disabled: !canAudit },
    { key: 'usage', label: '用量', onClick: onUsage, disabled: false },
    { key: 'recall', label: '语义召回', onClick: onRecall, disabled: false },
    { key: 'settings', label: '模型设置', onClick: onSettings, disabled: false },
  ]

  return (
    <div className="ml-auto flex shrink-0 items-center gap-1.5">
      <button type="button" onClick={onRefresh} className={BUTTON}>
        刷新
      </button>

      {/* 宽屏：次要操作平铺 */}
      <div className="hidden items-center gap-1.5 xl:flex">
        {secondary.slice(0, 3).map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={item.onClick}
            disabled={item.disabled}
            className={BUTTON}
          >
            {item.label}
          </button>
        ))}
        <div className="relative">
          <button
            type="button"
            onClick={() => setExportOpen((value) => !value)}
            disabled={!canExport}
            className={BUTTON}
          >
            导出报告
          </button>
          {exportOpen ? (
            <div className="absolute right-0 z-40 mt-1 w-32 overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg">
              {(['docx', 'md'] as const).map((format) => (
                <button
                  key={format}
                  type="button"
                  onClick={() => {
                    onExport(format)
                    setExportOpen(false)
                  }}
                  className="block w-full px-3 py-2 text-left text-xs text-slate-600 hover:bg-slate-50"
                >
                  {format === 'docx' ? 'Word (.docx)' : 'Markdown (.md)'}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <button type="button" onClick={onSettings} className={BUTTON}>
          模型设置
        </button>
      </div>

      {/* 窄屏：次要操作收进「更多」 */}
      <div className="relative xl:hidden" ref={moreRef}>
        <button
          type="button"
          onClick={() => setMoreOpen((value) => !value)}
          className={BUTTON}
          aria-haspopup="menu"
          aria-expanded={moreOpen}
        >
          更多
        </button>
        {moreOpen ? (
          <div
            role="menu"
            className="absolute right-0 z-40 mt-1 w-40 overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg"
          >
            {secondary.map((item) => (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  item.onClick()
                  setMoreOpen(false)
                }}
                className="block w-full px-3 py-2 text-left text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                {item.label}
              </button>
            ))}
            <div className="border-t border-slate-100">
              {(['docx', 'md'] as const).map((format) => (
                <button
                  key={format}
                  type="button"
                  role="menuitem"
                  disabled={!canExport}
                  onClick={() => {
                    onExport(format)
                    setMoreOpen(false)
                  }}
                  className="block w-full px-3 py-2 text-left text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
                >
                  导出 {format === 'docx' ? 'Word' : 'Markdown'}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <button
        type="button"
        onClick={onReview}
        disabled={!canReview}
        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {reviewing ? <Spinner className="h-3 w-3" /> : null}
        {reviewing ? '审阅中' : '运行审阅'}
      </button>
    </div>
  )
}
