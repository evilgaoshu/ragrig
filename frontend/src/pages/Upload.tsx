import { useCallback, useRef, useState } from 'react'
import { useKnowledgeBases, useUpload, useTask } from '../api/hooks'
import type { UploadResult } from '../api/types'

function TaskProgress({ taskId }: { taskId: string }) {
  const { data: task } = useTask(taskId)
  if (!task) return null

  const done = task.status === 'completed' || task.status === 'failed'
  const color =
    task.status === 'completed'
      ? 'text-emerald-600 bg-emerald-50'
      : task.status === 'failed'
        ? 'text-red-600 bg-red-50'
        : 'text-blue-600 bg-blue-50'

  return (
    <div className="flex items-center gap-2 mt-2">
      {!done && (
        <svg className="animate-spin h-3.5 w-3.5 text-blue-500" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
      )}
      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${color}`}>
        {task.status}
      </span>
      <span className="text-xs text-gray-500">pipeline task</span>
      {task.error && <span className="text-xs text-red-500 truncate">{task.error}</span>}
    </div>
  )
}

function ResultPanel({ result, onReset }: { result: UploadResult; onReset: () => void }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex gap-3">
          <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[80px]">
            <div className="text-[10px] font-bold uppercase text-gray-400">Accepted</div>
            <div className={`text-base font-bold ${result.accepted_files > 0 ? 'text-emerald-600' : 'text-gray-400'}`}>
              {result.accepted_files}
            </div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[80px]">
            <div className="text-[10px] font-bold uppercase text-gray-400">Rejected</div>
            <div className={`text-base font-bold ${result.rejected_files > 0 ? 'text-red-500' : 'text-gray-400'}`}>
              {result.rejected_files}
            </div>
          </div>
        </div>
        <button
          onClick={onReset}
          className="ml-auto text-xs text-brand hover:underline"
        >
          Upload more
        </button>
      </div>

      {result.accepted_files > 0 && <TaskProgress taskId={result.task_id} />}

      {result.warnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-1">
          <div className="text-[10px] font-bold uppercase text-amber-600">Warnings</div>
          {result.warnings.map((w, i) => (
            <div key={i} className="text-xs text-amber-700">{w}</div>
          ))}
        </div>
      )}

      {result.rejections.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-4 py-2 bg-gray-50 text-[11px] font-bold uppercase tracking-wider text-gray-400">
            Rejected files
          </div>
          {result.rejections.map((r, i) => (
            <div key={i} className="flex items-start gap-3 px-4 py-2 border-t border-gray-100">
              <span className="shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded text-red-600 bg-red-50">
                {r.reason}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-mono text-gray-700 truncate">{r.filename}</div>
                {r.detail && <div className="text-xs text-gray-400 mt-0.5">{r.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Upload() {
  const { data: kbs, isLoading: kbsLoading } = useKnowledgeBases()
  const upload = useUpload()

  const [kbName, setKbName] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [dragging, setDragging] = useState(false)
  const [result, setResult] = useState<UploadResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const addFiles = useCallback((incoming: FileList | File[]) => {
    const arr = Array.from(incoming)
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name))
      return [...prev, ...arr.filter((f) => !names.has(f.name))]
    })
  }, [])

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
    },
    [addFiles],
  )

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) addFiles(e.target.files)
    e.target.value = ''
  }

  const removeFile = (name: string) => setFiles((prev) => prev.filter((f) => f.name !== name))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!kbName || !files.length) return
    try {
      const r = await upload.mutateAsync({ kbName, files })
      setResult(r)
      setFiles([])
    } catch {
      // error shown via upload.error
    }
  }

  const reset = () => {
    setResult(null)
    upload.reset()
  }

  const formatBytes = (n: number) =>
    n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 ** 2).toFixed(1)} MB`

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Upload</h1>
        <p className="text-gray-500 text-sm mt-0.5">Upload files directly to a knowledge base</p>
      </div>

      {result ? (
        <ResultPanel result={result} onReset={reset} />
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* KB picker */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-600">Knowledge base</label>
            {kbsLoading ? (
              <div className="text-sm text-gray-400">Loading…</div>
            ) : (
              <select
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
                value={kbName}
                onChange={(e) => setKbName(e.target.value)}
                required
              >
                <option value="">— select a knowledge base —</option>
                {(kbs ?? []).map((kb) => (
                  <option key={kb.id} value={kb.name}>
                    {kb.name}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Drop zone */}
          <div
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
              dragging
                ? 'border-brand bg-brand/5'
                : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={onInputChange}
            />
            <div className="text-2xl mb-2">📄</div>
            <div className="text-sm font-medium text-gray-700">Drop files here or click to browse</div>
            <div className="text-xs text-gray-400 mt-1">Markdown, PDF, plain text, and more</div>
          </div>

          {/* File list */}
          {files.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-gray-50 text-[11px] font-bold uppercase tracking-wider text-gray-400">
                {files.length} file{files.length !== 1 ? 's' : ''} selected
              </div>
              {files.map((f) => (
                <div
                  key={f.name}
                  className="flex items-center gap-3 px-4 py-2 border-t border-gray-100"
                >
                  <span className="flex-1 text-xs font-mono text-gray-700 truncate">{f.name}</span>
                  <span className="shrink-0 text-xs text-gray-400">{formatBytes(f.size)}</span>
                  <button
                    type="button"
                    onClick={() => removeFile(f.name)}
                    className="shrink-0 text-gray-400 hover:text-red-500 text-sm leading-none"
                    aria-label="Remove"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Error */}
          {upload.isError && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {upload.error instanceof Error ? upload.error.message : 'Upload failed'}
            </div>
          )}

          <button
            type="submit"
            disabled={!kbName || !files.length || upload.isPending}
            className="px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {upload.isPending ? 'Uploading…' : `Upload ${files.length || ''} file${files.length !== 1 ? 's' : ''}`}
          </button>
        </form>
      )}
    </div>
  )
}
