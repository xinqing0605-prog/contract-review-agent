import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  api,
  errorMessage,
  type ModelInput,
  type PresetView,
  type ServiceModel,
  type ServiceView,
} from '../api/client'
import { ConfirmDialog } from './ConfirmDialog'
import { CloseButton, EyeButton, Spinner } from './ui'

interface Props {
  open: boolean
  onClose: () => void
}

type Dialog =
  | { type: 'service'; mode: 'create' | 'edit'; id: string; name: string; kind: string }
  | {
      type: 'model'
      mode: 'create' | 'edit'
      serviceId: string
      modelId: string
      name: string
      description: string
      base_url: string
      api_key: string
      key_hint: string
      originalBase: string
    }

const EMPTY_SERVICE = { name: '', kind: '大模型' }

/** 后端存的是 UTC 时间（SQLite datetime('now')），这里转成本地时区显示 */
function formatLocal(value: string): string {
  const iso = value.includes('T') ? value : value.replace(' ', 'T') + 'Z'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function ModelSettings({ open, onClose }: Props) {
  const [pendingConfirm, setPendingConfirm] = useState<{
    title: string
    message: string
    confirmText?: string
    action: () => void
  } | null>(null)
  const [services, setServices] = useState<ServiceView[]>([])
  const [presets, setPresets] = useState<PresetView[]>([])
  const [kinds, setKinds] = useState<string[]>(['大模型', '综合服务', '本地模型', '自定义'])
  const [loading, setLoading] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [reveal, setReveal] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)
  // 弹窗内的字段级错误：显示在对应输入框下方，输入时自动清除
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [dialogError, setDialogError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setDialog(null)
    setMessage(null)
    setQuery('')
    void api.services
      .list()
      .then((body) => {
        setServices(body.services)
        setPresets(body.presets)
        if (body.kinds?.length) setKinds(body.kinds)
        setSelectedId((current) => current ?? body.services[0]?.id ?? null)
      })
      .catch((cause: unknown) => setMessage({ tone: 'err', text: errorMessage(cause) }))
      .finally(() => setLoading(false))
  }, [open])

  useEffect(() => {
    setFieldErrors({})
    setDialogError(null)
  }, [dialog])

  const selected = services.find((item) => item.id === selectedId) ?? null
  const visible = useMemo(
    () => services.filter((item) => item.name.toLowerCase().includes(query.trim().toLowerCase())),
    [services, query],
  )

  if (!open) return null

  function apply(next: ServiceView[]) {
    setServices(next)
    if (!next.some((item) => item.id === selectedId)) setSelectedId(next[0]?.id ?? null)
  }

  async function run(key: string, action: () => Promise<{ services: ServiceView[] }>) {
    setBusy(key)
    setMessage(null)
    try {
      const body = await action()
      apply(body.services)
    } catch (cause) {
      setMessage({ tone: 'err', text: errorMessage(cause) })
    } finally {
      setBusy(null)
    }
  }

  async function submitDialog() {
    if (!dialog) return
    setBusy('dialog')
    setMessage(null)
    try {
      if (dialog.type === 'service') {
        const serviceName = dialog.name.trim()
        if (!serviceName) {
          setFieldErrors({ name: '请填写服务商名称' })
          return
        }
        if (services.some((item) => item.name === serviceName && item.id !== dialog.id)) {
          setFieldErrors({ name: `已经有同名服务商「${serviceName}」，换个名字` })
          return
        }
        const body =
          dialog.mode === 'create'
            ? await api.services.create({ name: serviceName, kind: dialog.kind })
            : await api.services.update(dialog.id, {
                name: serviceName,
                kind: dialog.kind,
              })
        setServices(body.services)
        if (dialog.mode === 'create') setSelectedId(body.services[body.services.length - 1]?.id ?? null)
        setMessage({ tone: 'ok', text: dialog.mode === 'create' ? '服务商已添加' : '服务商已保存' })
      } else {
        const payload: ModelInput = {
          name: dialog.name.trim(),
          description: dialog.description.trim(),
          base_url: dialog.base_url.trim(),
          api_key: dialog.api_key.trim(),
        }
        const localErrors: Record<string, string> = {}
        if (!payload.name) localErrors.name = '请填写模型标识'
        if (!payload.base_url) localErrors.base_url = '请填写完整接口地址'
        if (dialog.mode === 'create' && !payload.api_key) {
          localErrors.api_key = '请填写 API Key'
        }
        if (dialog.mode === 'edit' && !payload.api_key && !dialog.key_hint) {
          localErrors.api_key = '这个模型还没有 API Key，请填写'
        }
        const owner = services.find((item) => item.id === dialog.serviceId)
        if (
          owner?.models.some((item) => item.name === payload.name && item.id !== dialog.modelId)
        ) {
          localErrors.name = `这个服务商下已经有模型「${payload.name}」，换个标识`
        }
        if (Object.keys(localErrors).length > 0) {
          setFieldErrors(localErrors)
          return
        }
        const body =
          dialog.mode === 'create'
            ? await api.services.addModel(dialog.serviceId, payload)
            : await api.services.updateModel(dialog.serviceId, dialog.modelId, payload)
        apply(body.services)
        setMessage({ tone: 'ok', text: dialog.mode === 'create' ? '模型已添加' : '模型已保存' })
      }
      setDialog(null)
    } catch (cause) {
      setDialogError(errorMessage(cause))
    } finally {
      setBusy(null)
    }
  }

  function openModelDialog(service: ServiceView, model?: ServiceModel) {
    setReveal(false)
    if (model) {
      setDialog({
        type: 'model',
        mode: 'edit',
        serviceId: service.id,
        modelId: model.id,
        name: model.name,
        description: model.description,
        base_url: model.base_url,
        api_key: '',
        key_hint: model.key_hint,
        originalBase: model.base_url,
      })
    } else {
      const fallback = service.models[0]?.base_url ?? ''
      setDialog({
        type: 'model',
        mode: 'create',
        serviceId: service.id,
        modelId: '',
        name: '',
        description: '',
        base_url: fallback,
        api_key: '',
        key_hint: '',
        originalBase: fallback,
      })
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-8"
      role="dialog"
      aria-modal="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="flex h-[82vh] max-h-[780px] w-full max-w-5xl flex-col rounded-xl bg-white shadow-xl">
        <header className="flex shrink-0 items-center justify-between border-b border-slate-200 px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">模型服务</h2>
            <p className="text-[10px] text-slate-500">个人设置 · 服务商分组，模型各自保存地址与 Key</p>
          </div>
          <CloseButton onClick={onClose} />
        </header>

        {message ? (
          <p
            className={`mx-5 mt-3 shrink-0 rounded-md px-2.5 py-2 text-[11px] leading-5 ${
              message.tone === 'ok' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
            }`}
          >
            {message.text}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center gap-2 px-5 py-12 text-xs text-slate-500">
            <Spinner /> 读取配置…
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[280px_minmax(0,1fr)]">
            <aside className="flex min-h-0 flex-col border-b border-slate-200 p-3 md:border-b-0 md:border-r">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索服务商…"
                className="w-full shrink-0 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs outline-none focus:border-slate-400"
              />
              <ul className="scroll-thin mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto">
                {visible.map((service) => {
                  const active = service.id === selectedId
                  const enabled = service.models.some((item) => item.is_active)
                  return (
                    <li key={service.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(service.id)}
                        className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition ${
                          active ? 'bg-slate-100' : 'hover:bg-slate-50'
                        }`}
                      >
                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-slate-900 text-[9px] font-bold uppercase text-white">
                          {service.name.slice(0, 2)}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-xs font-medium text-slate-800">
                            {service.name}
                          </span>
                          <span className="block truncate text-[10px] text-slate-400">
                            {service.models.length} 个模型 · {service.kind}
                          </span>
                        </span>
                        {enabled ? <i className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> : null}
                      </button>
                    </li>
                  )
                })}
                {visible.length === 0 ? (
                  <li className="px-2 py-6 text-center text-[10px] text-slate-400">没有匹配的服务商</li>
                ) : null}
              </ul>
              <button
                type="button"
                onClick={() =>
                  setDialog({ type: 'service', mode: 'create', id: '', ...EMPTY_SERVICE })
                }
                className="mt-2 w-full shrink-0 rounded-md border border-slate-200 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50"
              >
                + 添加服务商
              </button>
            </aside>

            <section className="scroll-thin min-h-0 overflow-y-auto p-4">
              {selected ? (
                <>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <h3 className="text-base font-semibold text-slate-900">{selected.name}</h3>
                      <p className="mt-0.5 text-[11px] text-slate-500">
                        {selected.models.length} 个模型 · {selected.kind}
                      </p>
                    </div>
                    <div className="flex gap-1.5">
                      <button
                        type="button"
                        onClick={() =>
                          setDialog({
                            type: 'service',
                            mode: 'edit',
                            id: selected.id,
                            name: selected.name,
                            kind: selected.kind,
                          })
                        }
                        className="rounded-md border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
                      >
                        编辑服务商
                      </button>
                      <button
                        type="button"
                        onClick={() => openModelDialog(selected)}
                        className="rounded-md border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
                      >
                        + 添加模型
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          const service = selected
                          setPendingConfirm({
                            title: `删除服务商「${service.name}」？`,
                            message:
                              service.models.length > 0
                                ? `这个服务商下还有 ${service.models.length} 个模型，会连同连接配置一起删除。此操作不可撤销。`
                                : '删除后需要重新填写接口地址和 API Key，此操作不可撤销。',
                            confirmText: '删除服务商',
                            action: () => {
                              void run(`del-${service.id}`, () => api.services.remove(service.id))
                            },
                          })
                        }}
                        className="rounded-md border border-red-200 px-2.5 py-1 text-[11px] text-red-600 hover:bg-red-50"
                      >
                        删除服务商
                      </button>
                    </div>
                  </div>

                  <p className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-[10px] leading-5 text-slate-500">
                    服务商只是分组；API Key 与完整接口地址按模型保存，只有勾选「当前使用」的模型会用于审阅。
                  </p>

                  <ul className="mt-3 space-y-2">
                    {selected.models.map((model) => (
                      <li key={model.id} className="rounded-lg border border-slate-200 p-3">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="truncate text-xs font-semibold text-slate-800">
                                {model.name}
                              </span>
                              {model.is_active ? (
                                <span className="rounded-full bg-emerald-600 px-1.5 py-0.5 text-[9px] text-white">
                                  当前使用
                                </span>
                              ) : null}
                              {model.capability === 'embedding' ? (
                                <span className="rounded-full bg-sky-100 px-1.5 py-0.5 text-[9px] text-sky-700">
                                  向量模型
                                </span>
                              ) : model.capability === 'chat' ? (
                                <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] text-slate-600">
                                  对话模型
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-0.5 truncate text-[10px] text-slate-500">
                              {model.description || '未填写说明'} · {selected.kind} · {selected.name}
                            </p>
                          </div>
                          <span className="shrink-0 text-[10px] text-slate-400">
                            {model.verified_at ? `已验证 ${formatLocal(model.verified_at)}` : '未验证'}
                          </span>
                        </div>

                        <p className="mt-1.5 truncate font-mono text-[10px] text-slate-500">
                          {model.base_url}
                        </p>

                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          <span
                            className={`text-[10px] ${model.configured ? 'text-emerald-600' : 'text-slate-400'}`}
                          >
                            {model.configured ? `已配置 ${model.key_hint}` : '未配置 Key'}
                          </span>
                          <button
                            type="button"
                            disabled={busy !== null || !model.configured}
                            onClick={() =>
                              void run(`test-${model.id}`, () =>
                                api.services.testModel(selected.id, model.id),
                              )
                            }
                            className="rounded border border-slate-200 px-2 py-0.5 text-[10px] text-slate-600 hover:bg-slate-50 disabled:opacity-40"
                          >
                            {busy === `test-${model.id}` ? '测试中…' : '测试连接'}
                          </button>
                          {!model.is_active && model.capability !== 'embedding' ? (
                            <button
                              type="button"
                              disabled={busy !== null}
                              onClick={() =>
                                void run(`act-${model.id}`, () =>
                                  api.services.activateModel(selected.id, model.id),
                                )
                              }
                              className="rounded border border-slate-200 px-2 py-0.5 text-[10px] text-slate-600 hover:bg-slate-50 disabled:opacity-40"
                            >
                              设为当前
                            </button>
                          ) : null}
                          <button
                            type="button"
                            onClick={() => openModelDialog(selected, model)}
                            className="rounded border border-slate-200 px-2 py-0.5 text-[10px] text-slate-600 hover:bg-slate-50"
                          >
                            编辑模型
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                          const service = selected
                          setPendingConfirm({
                            title: `删除服务商「${service.name}」？`,
                            message:
                              service.models.length > 0
                                ? `这个服务商下还有 ${service.models.length} 个模型，会连同连接配置一起删除。此操作不可撤销。`
                                : '删除后需要重新填写接口地址和 API Key，此操作不可撤销。',
                            confirmText: '删除服务商',
                            action: () => {
                              void run(`del-${service.id}`, () => api.services.remove(service.id))
                            },
                          })
                        }}
                            className="rounded border border-slate-200 px-2 py-0.5 text-[10px] text-red-600 hover:bg-red-50"
                          >
                            删除模型
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>

                  {selected.models.length === 0 ? (
                    <div className="mt-3 rounded-lg border border-dashed border-slate-300 px-3 py-8 text-center text-[11px] text-slate-400">
                      这个服务商下还没有模型，点「+ 添加模型」创建第一个
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="flex h-full items-center justify-center text-[11px] text-slate-400">
                  左侧选择或新建一个服务商
                </div>
              )}
            </section>
          </div>
        )}
      </div>

      {dialog ? (
        <DialogShell
          title={
            dialog.type === 'service'
              ? dialog.mode === 'create'
                ? '添加服务商'
                : '编辑服务商'
              : dialog.mode === 'create'
                ? `添加 ${services.find((item) => item.id === dialog.serviceId)?.name ?? ''} 模型`
                : '编辑模型'
          }
          subtitle={
            dialog.type === 'service'
              ? '只填写服务商名称和类型，模型在右侧单独添加。'
              : '模型标识与完整接口地址共同决定实际调用。'
          }
          onClose={() => setDialog(null)}
        >
          {dialog.type === 'service' ? (
            <>
              <Field label="服务商名称" required error={fieldErrors.name}>
                <input
                  autoFocus
                  value={dialog.name}
                  onChange={(event) => setDialog({ ...dialog, name: event.target.value })}
                  placeholder="例如 Qwen"
                  className="w-full rounded-md border border-slate-200 px-2.5 py-2 text-xs outline-none focus:border-slate-400"
                />
              </Field>
              <Field label="服务商类型" required>
                <select
                  value={dialog.kind}
                  onChange={(event) => setDialog({ ...dialog, kind: event.target.value })}
                  className="w-full rounded-md border border-slate-200 px-2.5 py-2 text-xs outline-none focus:border-slate-400"
                >
                  {kinds.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </Field>
            </>
          ) : (
            <>
              <Field label="模型标识" required error={fieldErrors.name}>
                <input
                  autoFocus
                  value={dialog.name}
                  onChange={(event) => setDialog({ ...dialog, name: event.target.value })}
                  placeholder="qwen-plus"
                  className="w-full rounded-md border border-slate-200 px-2.5 py-2 font-mono text-xs outline-none focus:border-slate-400"
                />
              </Field>
              <Field label="完整 API 接口地址" required error={fieldErrors.base_url}>
                <input
                  value={dialog.base_url}
                  onChange={(event) => setDialog({ ...dialog, base_url: event.target.value })}
                  placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                  className="w-full rounded-md border border-slate-200 px-2.5 py-2 font-mono text-xs outline-none focus:border-slate-400"
                />
                <div className="mt-1 flex flex-wrap gap-1">
                  {presets.slice(0, 8).map((preset) => (
                    <button
                      key={preset.id}
                      type="button"
                      onClick={() => setDialog({ ...dialog, base_url: preset.base_url })}
                      className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-slate-50"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </Field>
              <Field
                label={dialog.mode === 'create' ? 'API Key' : '替换 API Key（留空则保留原 Key）'}
                required={dialog.mode === 'create' || !dialog.key_hint}
                error={fieldErrors.api_key}
              >
                <div className="relative">
                  <input
                    type={reveal ? 'text' : 'password'}
                    value={dialog.api_key}
                    onChange={(event) => setDialog({ ...dialog, api_key: event.target.value })}
                    placeholder={dialog.key_hint ? `当前 ${dialog.key_hint}` : 'sk-…'}
                    autoComplete="off"
                    className="w-full rounded-md border border-slate-200 py-2 pl-2.5 pr-9 font-mono text-xs outline-none focus:border-slate-400"
                  />
                  <div className="absolute right-1.5 top-1/2 -translate-y-1/2">
                    <EyeButton shown={reveal} onToggle={() => setReveal((value) => !value)} />
                  </div>
                </div>
              </Field>
              <Field label="模型说明（可选）">
                <input
                  value={dialog.description}
                  onChange={(event) => setDialog({ ...dialog, description: event.target.value })}
                  placeholder="例如：通义千问 对话模型"
                  className="w-full rounded-md border border-slate-200 px-2.5 py-2 text-xs outline-none focus:border-slate-400"
                />
              </Field>
            </>
          )}
          {dialogError ? (
            <p className="mt-3 rounded-md bg-red-50 px-2.5 py-2 text-[11px] leading-5 text-red-700">
              {dialogError}
            </p>
          ) : null}
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDialog(null)}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="button"
              disabled={busy === 'dialog'}
              onClick={() => void submitDialog()}
              className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {busy === 'dialog' ? <Spinner className="h-3 w-3" /> : null}
              {dialog.type === 'service'
                ? dialog.mode === 'create'
                  ? '添加服务商'
                  : '保存服务商'
                : dialog.mode === 'create'
                  ? '添加模型'
                  : '保存模型'}
            </button>
          </div>
        </DialogShell>
      ) : null}
    
      <ConfirmDialog
        open={pendingConfirm !== null}
        title={pendingConfirm?.title ?? ''}
        message={pendingConfirm?.message ?? ''}
        confirmText={pendingConfirm?.confirmText}
        onCancel={() => setPendingConfirm(null)}
        onConfirm={() => {
          const pending = pendingConfirm
          setPendingConfirm(null)
          pending?.action()
        }}
      />
    </div>
  )
}

function DialogShell({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string
  subtitle: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/50 p-4"
      role="dialog"
      aria-modal="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-lg rounded-xl bg-white p-5 shadow-2xl">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-900">{title}</h3>
            <p className="mt-0.5 text-[11px] text-slate-500">{subtitle}</p>
          </div>
          <CloseButton onClick={onClose} />
        </div>
        <div className="mt-4 space-y-3">{children}</div>
      </div>
    </div>
  )
}

function Field({
  label,
  required,
  error,
  children,
}: {
  label: string
  required?: boolean
  error?: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] text-slate-500">
        {label} {required ? <span className="text-red-500">*</span> : null}
      </span>
      {children}
      {error ? <span className="mt-1 block text-[10px] text-red-600">{error}</span> : null}
    </label>
  )
}
