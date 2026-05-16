import { useRetrievalBenchmarkRecent, useRetrievalBenchmarkIntegrity } from '../api/hooks'
import StatusCard from '../components/StatusCard'

function statusColor(s: string) {
  if (s === 'pass' || s === 'ok' || s === 'healthy') return 'text-emerald-600 bg-emerald-50 border-emerald-200'
  if (s === 'degraded' || s === 'warn') return 'text-amber-600 bg-amber-50 border-amber-200'
  return 'text-red-600 bg-red-50 border-red-200'
}

function JsonTree({ obj, depth = 0 }: { obj: unknown; depth?: number }) {
  if (obj === null || obj === undefined) return <span className="text-gray-400">null</span>
  if (typeof obj === 'boolean') return <span className={obj ? 'text-emerald-600' : 'text-red-500'}>{String(obj)}</span>
  if (typeof obj === 'number') return <span className="text-blue-600">{obj}</span>
  if (typeof obj === 'string') return <span className="text-gray-700">"{obj}"</span>
  if (Array.isArray(obj)) {
    if (obj.length === 0) return <span className="text-gray-400">[]</span>
    return (
      <div className={depth > 0 ? 'ml-3 border-l border-gray-100 pl-2' : ''}>
        {obj.map((v, i) => (
          <div key={i} className="py-0.5"><JsonTree obj={v} depth={depth + 1} /></div>
        ))}
      </div>
    )
  }
  if (typeof obj === 'object') {
    return (
      <div className={depth > 0 ? 'ml-3 border-l border-gray-100 pl-2' : ''}>
        {Object.entries(obj as Record<string, unknown>).map(([k, v]) => (
          <div key={k} className="py-0.5 flex gap-1.5 flex-wrap">
            <span className="text-gray-500 font-mono shrink-0">{k}:</span>
            <JsonTree obj={v} depth={depth + 1} />
          </div>
        ))}
      </div>
    )
  }
  return <span>{String(obj)}</span>
}

export default function RetrievalBenchmark() {
  const { data: recent, isLoading: recentLoading } = useRetrievalBenchmarkRecent()
  const { data: integrity, isLoading: integrityLoading } = useRetrievalBenchmarkIntegrity()

  const rec = recent as { available?: boolean; last_updated?: string; artifact_path?: string; summary?: Record<string, unknown> } | undefined
  const integ = integrity as { status?: string; reason?: string; checks?: Record<string, boolean>; generated_at?: string } | undefined

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Retrieval Benchmark</h1>
        <p className="text-gray-500 text-sm mt-0.5">Retrieval quality benchmark results</p>
      </div>

      {/* Integrity strip */}
      {!integrityLoading && integ && (
        <div className="flex gap-3 flex-wrap items-center">
          <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[90px]">
            <div className="text-[10px] font-bold uppercase text-gray-400">Integrity</div>
            <span className={`text-xs font-bold px-1.5 py-0.5 rounded border ${statusColor(integ.status ?? '')}`}>
              {integ.status ?? '—'}
            </span>
          </div>
          {integ.checks && Object.entries(integ.checks).map(([k, v]) => (
            <StatusCard key={k} label={k.replace(/_/g, ' ')} value={v ? 'pass' : 'fail'} status={v ? 'ok' : 'error'} />
          ))}
        </div>
      )}

      {recentLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : rec?.available === false ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center">
          <div className="text-sm font-medium text-gray-500">No benchmark artifact found</div>
          <div className="text-xs text-gray-400 mt-1">Run the retrieval benchmark to generate results.</div>
        </div>
      ) : rec ? (
        <div className="space-y-3">
          <div className="flex gap-3 text-xs text-gray-400">
            {rec.last_updated && <span>Updated: {new Date(rec.last_updated).toLocaleString()}</span>}
            {rec.artifact_path && <span className="font-mono">{rec.artifact_path}</span>}
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-4 text-xs font-mono overflow-x-auto">
            <JsonTree obj={rec.summary} />
          </div>
        </div>
      ) : null}
    </div>
  )
}
