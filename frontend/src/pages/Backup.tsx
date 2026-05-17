import { useState } from 'react'
import { useAdminStatus, useRestoreWorkspace } from '../api/hooks'
import { useAuth } from '../contexts/useAuth'

function CountTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-gray-200 bg-white p-3">
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
      <div className="text-lg font-bold text-gray-900 mt-1">{value.toLocaleString()}</div>
    </div>
  )
}

export default function Backup() {
  const { user } = useAuth()
  const workspaceId = user?.workspace_id ?? ''
  const { data: counts, isLoading } = useAdminStatus()
  const restore = useRestoreWorkspace()

  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null)

  const handleDownload = async () => {
    if (!workspaceId) return
    setDownloading(true)
    setError(null)
    try {
      const token = localStorage.getItem('ragrig_token')
      const res = await fetch(`/admin/backup/${workspaceId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail ?? body?.error ?? `HTTP ${res.status}`)
      }
      const payload = await res.json()
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-')
      a.href = url
      a.download = `ragrig-backup-${workspaceId.slice(0, 8)}-${stamp}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setDownloading(false)
    }
  }

  const handleFile = async (file: File) => {
    setError(null)
    setPreview(null)
    try {
      const text = await file.text()
      const parsed = JSON.parse(text) as Record<string, unknown>
      if (parsed.schema_version == null || !parsed.workspace) {
        throw new Error('not a RAGRig backup file (missing schema_version or workspace)')
      }
      setPreview(parsed)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleFile(file)
  }

  const handleRestore = () => {
    if (!preview) return
    restore.mutate(preview, {
      onSuccess: () => {
        setPreview(null)
      },
      onError: (e) => setError(e instanceof Error ? e.message : String(e)),
    })
  }

  const previewCounts = preview
    ? {
        knowledge_bases: ((preview.knowledge_bases as unknown[]) ?? []).length,
        sources: ((preview.sources as unknown[]) ?? []).length,
        conversations: ((preview.conversations as unknown[]) ?? []).length,
        feedback: ((preview.answer_feedback as unknown[]) ?? []).length,
        budgets: ((preview.budgets as unknown[]) ?? []).length,
        usage_events: ((preview.usage_events as unknown[]) ?? []).length,
        audit_events: ((preview.audit_events as unknown[]) ?? []).length,
      }
    : null

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Workspace Backup</h1>
        <p className="text-gray-500 text-sm mt-0.5">
          Export the workspace configuration + history as JSON, or restore from a previous dump.
        </p>
      </div>

      {/* Current counts */}
      <section>
        <h2 className="text-sm font-semibold text-gray-800 mb-2">Current install</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2">
          {isLoading || !counts ? (
            <div className="col-span-6 text-[11px] text-gray-400">Loading…</div>
          ) : (
            <>
              <CountTile label="Workspaces" value={counts.workspaces} />
              <CountTile label="Knowledge bases" value={counts.knowledge_bases} />
              <CountTile label="Sources" value={counts.sources} />
              <CountTile label="Conversations" value={counts.conversations} />
              <CountTile label="Feedback" value={counts.answer_feedback} />
              <CountTile label="Audit events" value={counts.audit_events} />
            </>
          )}
        </div>
      </section>

      {/* Export */}
      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-gray-800">Export</h2>
        <p className="text-[12px] text-gray-500 mt-1">
          Dumps workspace + KBs + sources (with webhook secrets) + conversations + feedback +
          budgets + usage events + API keys + audit. Chunks, embeddings, and document text are
          intentionally <strong>excluded</strong> — they re-derive from sources.
        </p>
        <div className="mt-3 flex items-center gap-3">
          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading || !workspaceId}
            className="rounded bg-brand text-white px-3 py-1.5 text-[13px] disabled:opacity-50"
          >
            {downloading ? 'Downloading…' : 'Download backup JSON'}
          </button>
          <span className="text-[11px] text-gray-400">workspace_id: {workspaceId || '—'}</span>
        </div>
      </section>

      {/* Restore */}
      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-gray-800">Restore</h2>
        <p className="text-[12px] text-gray-500 mt-1">
          Drop a backup JSON below. Restore upserts by id, so re-running with the same file is
          safe.
        </p>

        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={`mt-3 rounded border-2 border-dashed px-6 py-10 text-center transition-colors ${
            dragging ? 'border-brand bg-brand/5' : 'border-gray-300 bg-gray-50'
          }`}
        >
          <div className="text-[13px] text-gray-700">
            Drag &amp; drop a <code className="text-brand">.json</code> backup file here
          </div>
          <div className="text-[11px] text-gray-400 mt-1">or</div>
          <label className="mt-2 inline-block cursor-pointer rounded border border-gray-300 bg-white px-3 py-1 text-[12px] hover:bg-gray-100">
            <input
              type="file"
              accept="application/json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) handleFile(f)
              }}
            />
            Browse…
          </label>
        </div>

        {preview && previewCounts && (
          <div className="mt-4 rounded border border-amber-300 bg-amber-50 p-3">
            <div className="text-[12px] font-semibold text-amber-900">
              Ready to restore:
            </div>
            <div className="mt-1 text-[11px] text-amber-900 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-0.5">
              {Object.entries(previewCounts).map(([k, v]) => (
                <div key={k}>
                  {k.split('_').join(' ')}: <strong>{v}</strong>
                </div>
              ))}
            </div>
            <div className="mt-2 text-[11px] text-amber-900">
              schema_version:{' '}
              <code>{String((preview.schema_version as number) ?? '?')}</code>
              {preview.exported_at != null && (
                <> · exported_at: {String(preview.exported_at)}</>
              )}
            </div>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={handleRestore}
                disabled={restore.isPending}
                className="rounded bg-amber-600 text-white px-3 py-1 text-[12px] disabled:opacity-50"
              >
                {restore.isPending ? 'Restoring…' : 'Restore now'}
              </button>
              <button
                type="button"
                onClick={() => setPreview(null)}
                className="rounded border border-gray-300 px-3 py-1 text-[12px] text-gray-600 hover:bg-gray-100"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {restore.isSuccess && restore.data && (
          <div className="mt-3 rounded border border-green-300 bg-green-50 p-3 text-[11px] text-green-900">
            Restored — rows written:{' '}
            {Object.entries(restore.data.written ?? {})
              .filter(([, v]) => v > 0)
              .map(([k, v]) => `${k}=${v}`)
              .join(', ') || 'nothing (empty backup)'}
          </div>
        )}

        {error && (
          <div className="mt-3 rounded border border-red-300 bg-red-50 p-3 text-[12px] text-red-700">
            {error}
          </div>
        )}
      </section>
    </div>
  )
}
