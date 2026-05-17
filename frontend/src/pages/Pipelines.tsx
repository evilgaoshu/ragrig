import { useState } from 'react'
import {
  usePipelineRuns,
  usePipelineRunItems,
  useRetryPipelineRun,
  useRetryPipelineRunItem,
  useSources,
  useRunSourceIngest,
} from '../api/hooks'
import type { PipelineRun, PipelineRunItem } from '../api/types'

function statusColor(status: string): string {
  switch (status) {
    case 'completed': return 'text-emerald-600 bg-emerald-50'
    case 'failed':
    case 'error': return 'text-red-600 bg-red-50'
    case 'running': return 'text-blue-600 bg-blue-50'
    case 'skipped': return 'text-gray-500 bg-gray-100'
    default: return 'text-amber-600 bg-amber-50'
  }
}

function formatDuration(start: string, end: string | null): string {
  if (!end) return '—'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60_000).toFixed(1)}m`
}

// ── Item-level retry ──────────────────────────────────────────────────────

function RetryItemButton({ item }: { item: PipelineRunItem }) {
  const retry = useRetryPipelineRunItem()
  if (item.status !== 'failed') return null
  return (
    <button
      onClick={(e) => { e.stopPropagation(); retry.mutate(item.id) }}
      disabled={retry.isPending}
      className="shrink-0 text-[10px] px-1.5 py-0.5 rounded border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40 transition-colors"
      title="Retry this item"
    >
      {retry.isPending ? '…' : 'retry'}
    </button>
  )
}

// ── Run items list ────────────────────────────────────────────────────────

function RunItems({ runId }: { runId: string }) {
  const { data: items, isLoading } = usePipelineRunItems(runId)

  if (isLoading) return <div className="p-3 text-gray-400 text-sm">Loading items…</div>
  if (!items?.length) return <div className="p-3 text-gray-400 text-sm">No items.</div>

  const failed = items.filter((i) => i.status === 'failed')
  const rest = items.filter((i) => i.status !== 'failed')
  const ordered = [...failed, ...rest]

  return (
    <div className="border-t border-gray-200">
      <div className="px-4 py-2 bg-gray-50 text-[11px] font-bold uppercase tracking-wider text-gray-400">
        {items.length} items · {failed.length} failed
      </div>
      <div className="max-h-72 overflow-y-auto">
        {ordered.map((item: PipelineRunItem) => (
          <div
            key={item.id}
            className="flex items-start gap-3 px-4 py-2 border-b border-gray-100 last:border-0"
          >
            <span className={`shrink-0 mt-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${statusColor(item.status)}`}>
              {item.status}
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-mono text-gray-700 truncate">{item.document_uri}</div>
              {item.error && (
                <div className="text-xs text-red-500 mt-0.5 line-clamp-2">{item.error}</div>
              )}
            </div>
            <span className="shrink-0 text-[11px] text-gray-400">
              {formatDuration(item.started_at, item.finished_at)}
            </span>
            <RetryItemButton item={item} />
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Run row with retry ────────────────────────────────────────────────────

function RunRow({ run }: { run: PipelineRun }) {
  const [expanded, setExpanded] = useState(false)
  const retry = useRetryPipelineRun()

  const successPct =
    run.total_items > 0 ? Math.round((run.success_count / run.total_items) * 100) : null

  const canRetry = run.status === 'failed' || run.failure_count > 0

  return (
    <div className="border-b border-gray-200 last:border-0">
      <div className="w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors flex items-start gap-3">
        <button
          className="flex-1 flex items-start gap-3 min-w-0"
          onClick={() => setExpanded(!expanded)}
        >
          <span className={`shrink-0 mt-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${statusColor(run.status)}`}>
            {run.status}
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium text-gray-800">{run.knowledge_base}</span>
              <span className="text-xs text-gray-400">{run.run_type}</span>
              {run.source_uri && (
                <span className="text-xs font-mono text-gray-400 truncate max-w-xs">{run.source_uri}</span>
              )}
            </div>
            <div className="flex gap-4 mt-1 text-xs text-gray-500">
              <span>{run.total_items} items</span>
              {successPct !== null && <span>{successPct}% ok</span>}
              {run.failure_count > 0 && <span className="text-red-500">{run.failure_count} failed</span>}
              {run.skipped_count > 0 && <span>{run.skipped_count} skipped</span>}
              <span>{formatDuration(run.started_at, run.finished_at)}</span>
            </div>
            {run.error_message && (
              <div className="mt-1 text-xs text-red-500 line-clamp-1">{run.error_message}</div>
            )}
          </div>
          <div className="shrink-0 text-right text-xs text-gray-400 whitespace-nowrap">
            <div>{new Date(run.started_at).toLocaleDateString()}</div>
            <div>{new Date(run.started_at).toLocaleTimeString()}</div>
          </div>
          <span className="shrink-0 text-gray-400 text-sm">{expanded ? '▲' : '▼'}</span>
        </button>

        {canRetry && (
          <button
            onClick={(e) => { e.stopPropagation(); retry.mutate(run.id) }}
            disabled={retry.isPending && retry.variables === run.id}
            className="shrink-0 mt-0.5 text-xs px-2 py-1 rounded border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40 transition-colors"
            title="Retry all failed items in this run"
          >
            {retry.isPending && retry.variables === run.id ? 'Retrying…' : 'Retry failed'}
          </button>
        )}
      </div>

      {expanded && <RunItems runId={run.id} />}
    </div>
  )
}

// ── Trigger run from source ───────────────────────────────────────────────

function TriggerPanel({ onClose }: { onClose: () => void }) {
  const { data: sources, isLoading } = useSources()
  const runIngest = useRunSourceIngest()
  const [selectedId, setSelectedId] = useState('')
  const [taskId, setTaskId] = useState<string | null>(null)

  if (isLoading) return <div className="text-gray-400 text-sm p-4">Loading sources…</div>
  if (!sources?.length) {
    return (
      <div className="text-gray-500 text-sm p-4">
        No sources configured. Add a source on the{' '}
        <a href="/app/sources" className="text-brand hover:underline">Sources</a> page first.
      </div>
    )
  }

  const selected = sources.find((s) => s.id === selectedId)

  const handleRun = async () => {
    if (!selected) return
    const kindToPlugin: Record<string, string> = {
      fileshare: 'source.fileshare',
      s3: 'source.s3',
      local_directory: 'source.local',
    }
    const plugin_id = kindToPlugin[selected.kind] ?? `source.${selected.kind}`
    try {
      const res = await runIngest.mutateAsync({
        plugin_id,
        config: selected.config as Record<string, unknown>,
        knowledge_base: selected.knowledge_base ?? 'default',
      })
      setTaskId(res.task_id)
    } catch {
      // error shown inline
    }
  }

  return (
    <div className="border border-gray-200 bg-white rounded-lg p-4 space-y-3 max-w-lg">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-gray-800">Trigger ingestion from source</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
      </div>
      <select
        value={selectedId}
        onChange={(e) => setSelectedId(e.target.value)}
        className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
      >
        <option value="">— select a source —</option>
        {sources.map((s) => (
          <option key={s.id} value={s.id}>
            [{s.kind}] {s.knowledge_base} — {s.uri}
          </option>
        ))}
      </select>
      {runIngest.isError && (
        <div className="text-xs text-red-600">{runIngest.error?.message}</div>
      )}
      {taskId && (
        <div className="text-xs text-emerald-600">
          Ingestion enqueued — task {taskId.slice(0, 8)}… (view status in Pipelines list)
        </div>
      )}
      <div className="flex gap-2">
        <button
          onClick={handleRun}
          disabled={!selectedId || runIngest.isPending}
          className="px-3 py-1.5 bg-brand text-white text-sm rounded-lg hover:bg-brand/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {runIngest.isPending ? 'Starting…' : 'Run now'}
        </button>
        <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function Pipelines() {
  const { data: runs, isLoading } = usePipelineRuns()
  const [filter, setFilter] = useState<string>('all')
  const [kbFilter, setKbFilter] = useState<string>('all')
  const [showTrigger, setShowTrigger] = useState(false)

  const kbs = [...new Set((runs ?? []).map((r) => r.knowledge_base))].sort()
  const statuses = ['all', 'running', 'completed', 'failed']

  const filtered = (runs ?? []).filter((r) => {
    if (filter !== 'all' && r.status !== filter) return false
    if (kbFilter !== 'all' && r.knowledge_base !== kbFilter) return false
    return true
  })

  const summary = {
    total: runs?.length ?? 0,
    running: (runs ?? []).filter((r) => r.status === 'running').length,
    failed: (runs ?? []).filter((r) => r.status === 'failed').length,
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Pipelines</h1>
          <p className="text-gray-500 text-sm mt-0.5">Ingestion and indexing pipeline runs</p>
        </div>
        <button
          onClick={() => setShowTrigger((v) => !v)}
          className="px-3 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 transition-colors"
        >
          + Trigger run
        </button>
      </div>

      {showTrigger && <TriggerPanel onClose={() => setShowTrigger(false)} />}

      {/* Summary chips */}
      <div className="flex gap-3">
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[80px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Total</div>
          <div className="text-base font-bold text-gray-700">{summary.total}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[80px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Running</div>
          <div className={`text-base font-bold ${summary.running > 0 ? 'text-blue-600' : 'text-gray-400'}`}>
            {summary.running}
          </div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[80px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Failed</div>
          <div className={`text-base font-bold ${summary.failed > 0 ? 'text-red-500' : 'text-gray-400'}`}>
            {summary.failed}
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          {statuses.map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                filter === s ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        {kbs.length > 1 && (
          <select
            className="border border-gray-200 rounded-lg px-2 py-1 text-sm bg-white focus:outline-none"
            value={kbFilter}
            onChange={(e) => setKbFilter(e.target.value)}
          >
            <option value="all">All KBs</option>
            {kbs.map((kb) => (
              <option key={kb} value={kb}>{kb}</option>
            ))}
          </select>
        )}
      </div>

      {/* Runs list */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-6 text-gray-400 text-sm">Loading…</div>
        ) : !filtered.length ? (
          <div className="p-6 text-gray-400 text-sm text-center">
            {runs?.length ? 'No runs match the current filter.' : 'No pipeline runs yet. Upload a document or trigger a source ingestion to get started.'}
          </div>
        ) : (
          filtered.map((run) => <RunRow key={run.id} run={run} />)
        )}
      </div>
    </div>
  )
}
