import { useState } from 'react'
import { Spinner } from './ui'

interface Props {
  open: boolean
  busy: boolean
  onClose: () => void
  onSubmit: (name: string, text: string) => Promise<void>
}

const SAMPLE = `甲方应在收到发票并验收合格后九十日内支付全部款项，逾期付款不承担利息。
乙方在任何情况下不对间接损失、预期利润损失承担责任。
任一方未在合同期限届满前三十日书面通知终止的，本合同自动续期一年。`

export function PasteDialog({ open, busy, onClose, onSubmit }: Props) {
  const [name, setName] = useState('粘贴的合同')
  const [text, setText] = useState(SAMPLE)
  const [localError, setLocalError] = useState<string | null>(null)

  if (!open) return null

  const tooShort = text.trim().length < 20

  async function submit() {
    if (tooShort) {
      setLocalError('至少 20 个字符，后端会校验')
      return
    }
    setLocalError(null)
    try {
      await onSubmit(name.trim() || '未命名合同', text)
      onClose()
    } catch {
      setLocalError('导入失败，看页面顶部的错误提示')
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="粘贴合同文本"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-lg rounded-xl bg-white p-4 shadow-xl">
        <h2 className="text-sm font-semibold text-slate-900">粘贴合同文本</h2>
        <p className="mt-1 text-xs text-slate-500">当前后端只接受 UTF-8 纯文本，Word 请先另存为 txt。</p>

        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="合同名称"
          className="mt-3 w-full rounded-md border border-slate-200 px-2.5 py-1.5 text-xs outline-none focus:border-slate-400"
        />
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={7}
          className="scroll-thin mt-2 w-full resize-none rounded-md border border-slate-200 p-2.5 text-xs leading-6 outline-none focus:border-slate-400"
        />

        <div className="mt-2 flex items-center justify-between">
          <span className={`text-[10px] ${tooShort ? 'text-red-500' : 'text-slate-400'}`}>
            {text.trim().length} 字符{tooShort ? '（至少 20）' : ''}
            {localError ? ` · ${localError}` : ''}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => void submit()}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {busy ? <Spinner className="h-3 w-3" /> : null}
              导入
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
