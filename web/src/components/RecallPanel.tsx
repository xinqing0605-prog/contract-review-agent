import { useEffect, useState } from 'react'
import { api, errorMessage, type RecallSettings } from '../api/client'
import { CloseButton, Spinner } from './ui'

export function RecallPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [enabled, setEnabled] = useState(false)
  const [modelId, setModelId] = useState('')
  const [threshold, setThreshold] = useState(0.82)
  const [models, setModels] = useState<RecallSettings['models']>([])
  const [bounds, setBounds] = useState({ min: 0.6, max: 0.95, default: 0.82 })
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  // 只列确认支持 /embeddings 的模型；对话模型不该出现在这里
  const vectorModels = models.filter((model) => model.capability === 'embedding')

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError('')
    setSaved(false)
    api.recall
      .get()
      .then((body) => {
        if (cancelled) return
        setEnabled(body.settings.enabled)
        setModelId(body.settings.model_id)
        setThreshold(body.settings.threshold)
        setModels(body.models)
        setBounds(body.bounds)
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open])

  async function handleSave() {
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const body = await api.recall.save({ enabled, model_id: modelId, threshold })
      setModels(body.models)
      setSaved(true)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-16"
      role="dialog"
      aria-modal="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">语义召回</h2>
            <p className="mt-0.5 text-[11px] text-slate-500">
              规则漏掉的同义表述，用向量相似度补一条候选条款
            </p>
          </div>
          <CloseButton onClick={onClose} />
        </div>

        {loading ? (
          <p className="mt-4 inline-flex items-center gap-1.5 text-xs text-slate-400">
            <Spinner className="h-3 w-3" /> 加载中
          </p>
        ) : (
          <div className="mt-4 space-y-4">
            <label className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2">
              <span>
                <span className="text-xs font-medium text-slate-800">开启语义召回</span>
                <span className="mt-0.5 block text-[10px] text-slate-500">
                  关闭时只用规则，不产生向量调用费用
                </span>
              </span>
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
                className="h-4 w-4 accent-slate-900"
              />
            </label>

            <div>
              <label className="text-xs font-medium text-slate-800">向量模型</label>
              <select
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs text-slate-700"
              >
                <option value="">未选择</option>
                {vectorModels.map((model) => (
                  <option key={model.id} value={model.id} disabled={!model.configured}>
                    {model.service} · {model.name}
                    {model.configured ? '' : '（缺少 Key）'}
                  </option>
                ))}
              </select>
              {vectorModels.length === 0 ? (
                <p className="mt-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[10px] leading-relaxed text-amber-700">
                  还没有可用的向量模型。请到「模型设置」添加一个支持 <code>/embeddings</code> 的模型
                  （如通义 text-embedding-v3、BAAI/bge-m3），点「测试连接」确认后会出现在这里。
                </p>
              ) : (
                <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
                  只列出已确认为向量模型的条目。审阅用的对话模型在顶部「模型设置」里单独选择，两者互不影响。
                </p>
              )}
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label className="text-xs font-medium text-slate-800">相似度阈值</label>
                <span className="text-xs tabular-nums text-slate-600">{threshold.toFixed(2)}</span>
              </div>
              <input
                type="range"
                min={bounds.min}
                max={bounds.max}
                step={0.01}
                value={threshold}
                onChange={(event) => setThreshold(Number(event.target.value))}
                className="mt-1 w-full accent-slate-900"
              />
              <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
                越高越保守（少误报），越低越激进（多召回）。默认 {bounds.default.toFixed(2)}，建议先按
                默认跑一轮评测再调整。
              </p>
            </div>

            {error ? <p className="text-xs text-red-600">{error}</p> : null}
            {saved ? <p className="text-xs text-emerald-600">已保存，下次审阅生效</p> : null}

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
              >
                关闭
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={saving}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {saving ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
