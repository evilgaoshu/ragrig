import { useAnswerLiveSmoke } from '../api/hooks'
import StatusCard from '../components/StatusCard'

function statusOf(s: string | undefined): 'ok' | 'warn' | 'error' | 'neutral' {
  if (!s) return 'neutral'
  if (s === 'healthy' || s === 'ok' || s === 'pass') return 'ok'
  if (s === 'degraded' || s === 'skip') return 'warn'
  return 'error'
}

export default function AnswerLiveSmoke() {
  const { data, isLoading } = useAnswerLiveSmoke()

  const smoke = data as {
    available?: boolean
    status?: string
    reason?: string
    provider?: string
    model?: string
    citation_count?: number
    latency_ms?: number
    artifact_path?: string
    generated_at?: string
    stale?: boolean
    checks?: Record<string, unknown>
  } | undefined

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Answer Live Smoke</h1>
        <p className="text-gray-500 text-sm mt-0.5">LLM answer pipeline health</p>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : smoke?.available === false ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center space-y-1">
          <div className="text-sm font-medium text-gray-500">No smoke test artifact found</div>
          {smoke.reason && <div className="text-xs text-gray-400">{smoke.reason}</div>}
        </div>
      ) : smoke ? (
        <>
          <div className="flex gap-3 flex-wrap">
            <StatusCard label="Status" value={smoke.status ?? '—'} status={statusOf(smoke.status)} />
            {smoke.provider && <StatusCard label="Provider" value={smoke.provider} />}
            {smoke.model && <StatusCard label="Model" value={smoke.model} />}
            {smoke.citation_count !== undefined && (
              <StatusCard label="Citations" value={smoke.citation_count} status={smoke.citation_count > 0 ? 'ok' : 'warn'} />
            )}
            {smoke.latency_ms !== undefined && (
              <StatusCard label="Latency" value={`${smoke.latency_ms}ms`} />
            )}
            {smoke.stale && (
              <StatusCard label="Freshness" value="stale" status="warn" />
            )}
          </div>

          {smoke.reason && (
            <div className={`text-sm rounded-lg px-4 py-3 border ${
              statusOf(smoke.status) === 'error' ? 'bg-red-50 border-red-200 text-red-700' :
              statusOf(smoke.status) === 'warn' ? 'bg-amber-50 border-amber-200 text-amber-700' :
              'bg-gray-50 border-gray-200 text-gray-600'
            }`}>
              {smoke.reason}
            </div>
          )}

          {smoke.checks && Object.keys(smoke.checks).length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                Checks
              </div>
              {Object.entries(smoke.checks).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 last:border-0">
                  <span className="text-sm text-gray-700">{k.replace(/_/g, ' ')}</span>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${
                    v === true ? 'text-emerald-700 bg-emerald-50 border-emerald-200' :
                    v === false ? 'text-red-700 bg-red-50 border-red-200' :
                    'text-gray-500 bg-gray-100 border-gray-200'
                  }`}>{String(v)}</span>
                </div>
              ))}
            </div>
          )}

          <div className="text-xs text-gray-400 space-y-0.5">
            {smoke.generated_at && <div>Generated: {new Date(smoke.generated_at).toLocaleString()}</div>}
            {smoke.artifact_path && <div className="font-mono">{smoke.artifact_path}</div>}
          </div>
        </>
      ) : null}
    </div>
  )
}
