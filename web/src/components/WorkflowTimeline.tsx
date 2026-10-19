import type { ReviewMode, TraceStep } from '../types'
import { EmptyState, Spinner } from './ui'

interface Props {
  steps: TraceStep[]
  reviewing: boolean
  mode: ReviewMode | null
  durationMs: number | null
  modelError: string | null
  /** 文档已有历史条款但本次没跑过审阅时的说明，避免状态自相矛盾 */
  hint?: string | null
}

const ICON: Record<TraceStep['status'], string> = {
  success: 'text-emerald-600',
  skipped: 'text-slate-400',
  error: 'text-red-600',
  running: 'text-slate-500',
}

export function WorkflowTimeline({ steps, reviewing, mode, durationMs, modelError, hint }: Props) {
  if (steps.length === 0) {
    return (
      <EmptyState
        title="审阅链路"
        hint={
          hint ??
          '点击「运行审阅」后，这里展示后端真实返回的每一步，不是前端假动画。'
        }
      />
    )
  }

  return (
    <div className="px-4 pb-3 pt-2">
      <div className="mb-2 flex items-center justify-between text-[10px] text-slate-400">
        <span>
          {mode === 'deepseek'
            ? 'DeepSeek 已介入'
            : mode === 'demo'
              ? '规则降级（未配置模型或调用失败）'
              : reviewing
                ? '请求进行中'
                : '—'}
        </span>
        <span>{durationMs !== null ? `总耗时 ${Math.round(durationMs)} ms` : ''}</span>
      </div>

      <ol className="space-y-2.5">
        {steps.map((step, index) => (
          <li key={`${step.step}-${index}`} className="flex gap-2.5">
            <span
              className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-[9px] font-semibold ${ICON[step.status]}`}
            >
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <p className="truncate text-xs font-medium text-slate-800">{step.step}</p>
                {step.status === 'running' ? <Spinner /> : null}
                {step.status === 'skipped' ? (
                  <span className="text-[9px] text-slate-400">跳过</span>
                ) : null}
                {step.status === 'error' ? (
                  <span className="text-[9px] text-red-500">失败</span>
                ) : null}
              </div>
              <p className="mt-0.5 break-words text-[11px] leading-5 text-slate-500">{step.detail}</p>
            </div>
          </li>
        ))}
      </ol>

      {modelError ? (
        <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] leading-5 text-amber-800">
          已自动降级为规则审阅：{modelError}
        </p>
      ) : null}
    </div>
  )
}
