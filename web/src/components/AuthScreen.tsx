import { useState, type FormEvent } from 'react'
import { errorMessage } from '../api/client'
import { Spinner } from './ui'

interface Props {
  error: string | null
  onLogin: (account: string, password: string) => Promise<void>
  onRegister: (account: string, password: string, name: string) => Promise<void>
  onDismissError: () => void
}

type Mode = 'login' | 'register'
type FieldErrors = { account?: string; password?: string; confirm?: string }

const STRENGTH_LABEL = ['太弱', '偏弱', '中等', '较强', '很强']

function passwordChecks(value: string) {
  const classes = [
    /[a-z]/.test(value),
    /[A-Z]/.test(value),
    /\d/.test(value),
    /[^A-Za-z0-9]/.test(value),
  ]
  const count = classes.filter(Boolean).length
  const lengthOk = value.length >= 8
  const longEnough = value.length >= 12
  const ok = lengthOk && count >= 3
  let score = 0
  if (value.length > 0) score = 1
  if (lengthOk) score = 2
  if (lengthOk && count >= 3) score = 3
  if (lengthOk && count >= 3 && longEnough) score = 4
  return { classes, count, lengthOk, ok, score }
}

export function AuthScreen({ error, onLogin, onRegister, onDismissError }: Props) {
  const [mode, setMode] = useState<Mode>('login')
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [serverError, setServerError] = useState<string | null>(null)

  const isRegister = mode === 'register'
  const checks = passwordChecks(password)

  function validate(): FieldErrors {
    const next: FieldErrors = {}
    const value = account.trim()

    if (!value) next.account = '请输入邮箱或用户名'
    else if (value.includes('@')) {
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) next.account = '邮箱格式不正确'
    } else if (!/^[\w\u4e00-\u9fa5.-]{3,20}$/.test(value)) {
      next.account = '用户名需 3–20 位，可用中文、字母、数字、下划线'
    }

    if (!password) next.password = '请输入密码'
    else if (isRegister && !checks.ok) {
      next.password = '密码需至少 8 位，且包含大小写字母、数字、符号中的至少三类'
    }

    if (isRegister) {
      if (!confirm) next.confirm = '请再次输入密码'
      else if (confirm !== password) next.confirm = '两次输入的密码不一致'
    }
    return next
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    onDismissError()
    setServerError(null)

    const found = validate()
    if (Object.keys(found).length > 0) {
      setErrors(found)
      return
    }
    setErrors({})
    setBusy(true)
    try {
      if (isRegister) await onRegister(account.trim(), password, name)
      else await onLogin(account.trim(), password)
    } catch (cause) {
      setServerError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  const shownError = serverError ?? error

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 text-sm font-bold text-white">
            CG
          </div>
          <div>
            <h1 className="text-base font-semibold text-slate-900">ClauseGuard</h1>
            <p className="text-xs text-slate-500">AI 合同审阅工作台</p>
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex rounded-lg bg-slate-100 p-1">
            {(['login', 'register'] as Mode[]).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => {
                  setMode(item)
                  setErrors({})
                  setServerError(null)
                  onDismissError()
                }}
                className={`flex-1 rounded-md py-1.5 text-xs font-medium transition ${
                  mode === item ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'
                }`}
              >
                {item === 'login' ? '登录' : '注册'}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-3" noValidate>
            {isRegister ? (
              <label className="block">
                <span className="text-[11px] text-slate-500">昵称（可空）</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  className="mt-1 w-full rounded-md border border-slate-200 px-2.5 py-2 text-sm outline-none focus:border-slate-400"
                  placeholder="怎么称呼你"
                />
              </label>
            ) : null}

            <label className="block">
              <span className="text-[11px] text-slate-500">
                邮箱或用户名 <span className="text-red-500">*</span>
              </span>
              <input
                autoComplete="username"
                value={account}
                onChange={(event) => {
                  setAccount(event.target.value)
                  setErrors((current) => ({ ...current, account: undefined }))
                }}
                placeholder="you@example.com 或 用户名"
                className={`mt-1 w-full rounded-md border px-2.5 py-2 text-sm outline-none ${
                  errors.account
                    ? 'border-red-300 focus:border-red-400'
                    : 'border-slate-200 focus:border-slate-400'
                }`}
              />
              {errors.account ? (
                <span className="mt-1 block text-[10px] text-red-600">{errors.account}</span>
              ) : null}
            </label>

            <label className="block">
              <span className="text-[11px] text-slate-500">
                密码 {isRegister ? '（至少 8 位）' : ''} <span className="text-red-500">*</span>
              </span>
              <input
                type="password"
                autoComplete={isRegister ? 'new-password' : 'current-password'}
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value)
                  setErrors((current) => ({ ...current, password: undefined }))
                }}
                placeholder="••••••••"
                className={`mt-1 w-full rounded-md border px-2.5 py-2 text-sm outline-none ${
                  errors.password
                    ? 'border-red-300 focus:border-red-400'
                    : 'border-slate-200 focus:border-slate-400'
                }`}
              />
              {errors.password ? (
                <span className="mt-1 block text-[10px] text-red-600">{errors.password}</span>
              ) : null}
              {isRegister && password ? (
                <div className="mt-1.5 space-y-1">
                  <div className="flex items-center gap-1">
                    {[0, 1, 2, 3].map((index) => (
                      <span
                        key={index}
                        className={`h-1 flex-1 rounded-full ${
                          index < checks.score
                            ? checks.score <= 1
                              ? 'bg-red-400'
                              : checks.score === 2
                                ? 'bg-amber-400'
                                : 'bg-emerald-500'
                            : 'bg-slate-200'
                        }`}
                      />
                    ))}
                    <span className="ml-1 w-10 shrink-0 text-right text-[10px] text-slate-500">
                      {STRENGTH_LABEL[checks.score]}
                    </span>
                  </div>
                  <ul className="flex flex-wrap gap-x-3 text-[10px]">
                    <li className={checks.lengthOk ? 'text-emerald-600' : 'text-slate-400'}>
                      ≥ 8 位
                    </li>
                    <li
                      className={
                        checks.classes[0] || checks.classes[1] ? 'text-emerald-600' : 'text-slate-400'
                      }
                    >
                      字母
                    </li>
                    <li className={checks.classes[2] ? 'text-emerald-600' : 'text-slate-400'}>
                      数字
                    </li>
                    <li className={checks.classes[3] ? 'text-emerald-600' : 'text-slate-400'}>
                      符号
                    </li>
                    <li className="text-slate-400">（至少三类）</li>
                  </ul>
                </div>
              ) : null}
            </label>

            {isRegister ? (
              <label className="block">
                <span className="text-[11px] text-slate-500">
                  确认密码 <span className="text-red-500">*</span>
                </span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(event) => {
                    setConfirm(event.target.value)
                    setErrors((current) => ({ ...current, confirm: undefined }))
                  }}
                  placeholder="再输入一次"
                  className={`mt-1 w-full rounded-md border px-2.5 py-2 text-sm outline-none ${
                    errors.confirm
                      ? 'border-red-300 focus:border-red-400'
                      : 'border-slate-200 focus:border-slate-400'
                  }`}
                />
                {errors.confirm ? (
                  <span className="mt-1 block text-[10px] text-red-600">{errors.confirm}</span>
                ) : null}
              </label>
            ) : null}

            {shownError ? (
              <p className="rounded-md bg-red-50 px-2.5 py-2 text-[11px] leading-5 text-red-700">
                {shownError}
              </p>
            ) : null}

            <button
              type="submit"
              disabled={busy}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-slate-900 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {busy ? <Spinner className="h-3.5 w-3.5" /> : null}
              {isRegister ? '注册并进入' : '登录'}
            </button>
          </form>

          <p className="mt-4 rounded-md bg-slate-50 px-2.5 py-2 text-[10px] leading-5 text-slate-500">
            本地演示账号：<code>demo@clauseguard.local</code> / <code>demo1234</code>
            <br />
            账号可以是邮箱，也可以是用户名（3–20 位）。
          </p>
        </div>
      </div>
    </div>
  )
}
