import { useRef, useState } from 'react'
import type { DocumentRecord } from '../types'
import { ConfirmDialog } from './ConfirmDialog'
import { EmptyState } from './ui'

interface Props {
  documents: DocumentRecord[]
  activeId: string | null
  onSelect: (id: string) => void
  onCompose: () => void
  onUploadFile: (file: File) => void
  onRemove: (id: string) => void
}

export function DocumentPanel({
  documents,
  activeId,
  onSelect,
  onCompose,
  onUploadFile,
  onRemove,
}: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [pendingDelete, setPendingDelete] = useState<DocumentRecord | null>(null)

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1.5 border-b border-slate-100 px-2 py-2">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="flex-1 rounded-md bg-slate-900 px-2 py-1.5 text-[11px] font-medium text-white hover:bg-slate-800"
        >
          上传文件
        </button>
        <button
          type="button"
          onClick={onCompose}
          className="rounded-md border border-slate-200 px-2 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50"
        >
          粘贴
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".txt,.md,.docx,.pdf"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) onUploadFile(file)
            event.target.value = ''
          }}
        />
      </div>

      {documents.length === 0 ? (
        <EmptyState
          title="还没有合同"
          hint="支持 TXT / Markdown / Word / PDF，上传后数据会保存到你的账号下。"
        />
      ) : (
        <ul className="space-y-1 p-2">
          {documents.map((document) => {
            const clauses = document.clauses ?? []
            const high = clauses.filter((clause) => clause.risk === 'high').length
            const active = document.id === activeId
            return (
              <li key={document.id} className="group relative">
                <button
                  type="button"
                  onClick={() => onSelect(document.id)}
                  aria-current={active}
                  className={`w-full rounded-lg border px-2.5 py-2 pr-7 text-left transition ${
                    active
                      ? 'border-slate-900 bg-slate-50'
                      : 'border-transparent hover:border-slate-200 hover:bg-slate-50'
                  }`}
                >
                  <p className="truncate text-xs font-medium text-slate-800">{document.name}</p>
                  <p className="mt-1 flex items-center justify-between text-[10px] text-slate-400">
                    <span className="uppercase">{document.source_type}</span>
                    <span>
                      {document.status === 'reviewed' ? '已审阅' : '待审阅'} · {clauses.length} 条
                      {high > 0 ? (
                        <em className="ml-1 font-medium not-italic text-red-500">{high} 高</em>
                      ) : null}
                    </span>
                  </p>
                </button>
                <button
                  type="button"
                  title="删除"
                  onClick={() => setPendingDelete(document)}
                  className="absolute right-1.5 top-1.5 hidden h-5 w-5 items-center justify-center rounded text-[11px] text-slate-400 hover:bg-red-50 hover:text-red-600 group-hover:flex"
                >
                  ×
                </button>
              </li>
            )
          })}
        </ul>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={`删除「${pendingDelete?.name ?? ''}」？`}
        message="合同和条款会从列表移除，审计记录保留在数据库中。此操作不可撤销。"
        confirmText="删除合同"
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) onRemove(pendingDelete.id)
          setPendingDelete(null)
        }}
      />
    </div>
  )
}
