import { useState } from 'react'
import { useCostLatency, useKnowledgeBases } from '../api/hooks'
import StatusCard from '../components/StatusCard'

function statusChipClass(status: string) {
  if (status === 'completed') return 'text-emerald-700 bg-emerald-50 border-emerald-200'
  if (status === 'failed') return 'text-red-700 bg-red-50 border-red-200'
  if (status === 'running') return 'text-amber-700 bg-amber-50 border-amber-200'
  return 'text-gray-500 bg-gray-100 border-gray-200'
}

function formatDuration(ms: number): string {
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m ${s}s`
}

interface ModelStats {
  operation_count?: number
  total_tokens_estimated?: number
  total_cost_usd_estimated?: number
  [key: string]: unknown
}

interface RunRecord {
  id?: string
  knowledge_base?: string | null
  source_uri?: string | null
  run_type?: string
  status?: string
  started_at?: string
  finished_at?: string
  duration_ms?: number | null
  cost_latency_summary?: unknown
  [key: string]: unknown
}

interface Aggregate {
  operation_count?: number
  total_tokens_estimated?: number
  total_cost_usd_estimated?: number
  by_model?: Record<string, ModelStats>
  by_operation?: Record<string, unknown>
  [key: string]: unknown
}

interface CostLatencyData {
  schema_version?: string
  knowledge_base?: string | null
  run_count?: number
  tracked_operation_count?: number
  aggregate?: Aggregate
  runs?: RunRecord[]
  [key: string]: unknown
}

export default function CostLatency() {
  const { data: kbs } = useKnowledgeBases()
  const [selectedKb, setSelectedKb] = useState<string>('')

  const { data, isLoading } = useCostLatency(selectedKb || undefined, 20)

  const d = data as CostLatencyData | undefined
  const agg = d?.aggregate
  const runs = (d?.runs ?? []) as RunRecord[]
  const byModel = agg?.by_model ? Object.entries(agg.by_model) : []

  const isEmpty = !d || d.run_count === 0 || !agg

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Cost &amp; Latency</h1>
          <p className="text-gray-500 text-sm mt-0.5">Pipeline cost and latency tracking</p>
        </div>

        {/* KB filter */}
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 font-medium" htmlFor="kb-filter">
            Knowledge Base
          </label>
          <select
            id="kb-filter"
            value={selectedKb}
            onChange={(e) => setSelectedKb(e.target.value)}
            className="text-sm border border-gray-200 rounded px-2 py-1 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-brand/30"
          >
            <option value="">All KBs</option>
            {(kbs ?? []).map((kb) => (
              <option key={kb.name} value={kb.name}>
                {kb.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : isEmpty ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
          <div className="text-sm font-medium text-gray-500">No tracked runs yet</div>
          <div className="text-xs text-gray-400 mt-1">
            Run a pipeline to start collecting cost and latency data.
          </div>
        </div>
      ) : (
        <>
          {/* Summary cards */}
          <div className="flex gap-3 flex-wrap">
            <StatusCard
              label="Tracked Ops"
              value={(agg!.operation_count ?? 0).toLocaleString()}
            />
            <StatusCard
              label="Total Tokens"
              value={(agg!.total_tokens_estimated ?? 0).toLocaleString()}
            />
            <StatusCard
              label="Est. Cost USD"
              value={`$${(agg!.total_cost_usd_estimated ?? 0).toFixed(6)}`}
            />
            <StatusCard
              label="Runs"
              value={d!.run_count ?? 0}
            />
          </div>

          {/* By-model breakdown */}
          {byModel.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-200">
                <span className="text-xs font-bold uppercase tracking-wider text-gray-400">
                  By Model
                </span>
              </div>
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[1fr_auto_auto_auto] gap-4 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                <div>Model</div>
                <div className="text-right">Ops</div>
                <div className="text-right">Tokens</div>
                <div className="text-right">Cost USD</div>
              </div>
              {byModel.map(([model, stats]) => (
                <div
                  key={model}
                  className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[1fr_auto_auto_auto] gap-4 items-center"
                >
                  <div className="text-sm font-mono text-gray-800 truncate">{model}</div>
                  <div className="text-sm text-gray-700 text-right">
                    {(stats.operation_count ?? 0).toLocaleString()}
                  </div>
                  <div className="text-sm text-gray-700 text-right">
                    {(stats.total_tokens_estimated ?? 0).toLocaleString()}
                  </div>
                  <div className="text-sm text-gray-700 text-right font-mono">
                    ${(stats.total_cost_usd_estimated ?? 0).toFixed(6)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Runs table */}
          {runs.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-200">
                <span className="text-xs font-bold uppercase tracking-wider text-gray-400">
                  Runs
                </span>
              </div>
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-4 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                <div>KB</div>
                <div>Type</div>
                <div>Status</div>
                <div className="text-right">Duration</div>
                <div>Started At</div>
                <div className="text-right">Has Cost Data</div>
              </div>
              {runs.map((run, idx) => (
                <div
                  key={run.id ?? idx}
                  className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-4 items-center"
                >
                  <div className="text-sm text-gray-800 truncate font-mono">
                    {run.knowledge_base ?? '—'}
                  </div>
                  <div className="text-sm text-gray-600">{run.run_type ?? '—'}</div>
                  <div>
                    {run.status ? (
                      <span
                        className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${statusChipClass(run.status)}`}
                      >
                        {run.status}
                      </span>
                    ) : (
                      <span className="text-gray-400 text-sm">—</span>
                    )}
                  </div>
                  <div className="text-sm text-gray-600 text-right">
                    {run.duration_ms != null ? formatDuration(run.duration_ms) : '—'}
                  </div>
                  <div className="text-xs text-gray-400">
                    {run.started_at
                      ? new Date(run.started_at).toLocaleString()
                      : '—'}
                  </div>
                  <div className="text-right text-sm">
                    {run.cost_latency_summary != null ? (
                      <span className="text-emerald-600 font-medium">✓</span>
                    ) : (
                      <span className="text-gray-300">–</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
