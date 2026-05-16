import { useRetrievalBenchmarkIntegrity } from '../api/hooks'
import StatusCard from '../components/StatusCard'

function chipColor(ok: boolean) {
  return ok
    ? 'text-emerald-700 bg-emerald-50 border-emerald-200'
    : 'text-red-700 bg-red-50 border-red-200'
}

export default function BaselineIntegrity() {
  const { data, isLoading } = useRetrievalBenchmarkIntegrity()

  const integ = data as {
    status?: string
    reason?: string
    checks?: Record<string, boolean>
    generated_at?: string
    artifact_path?: string
    manifest_entries?: number
    hash_mismatches?: number
    schema_ok?: boolean
    freshness_days?: number
    stale?: boolean
  } | undefined

  function statusOf(s: string | undefined): 'ok' | 'warn' | 'error' | 'neutral' {
    if (!s) return 'neutral'
    if (s === 'pass' || s === 'ok' || s === 'healthy') return 'ok'
    if (s === 'degraded') return 'warn'
    return 'error'
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Baseline Integrity</h1>
        <p className="text-gray-500 text-sm mt-0.5">Retrieval benchmark baseline health check</p>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : !integ ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center">
          <div className="text-sm text-gray-500">No integrity data available</div>
        </div>
      ) : (
        <>
          <div className="flex gap-3 flex-wrap">
            <StatusCard
              label="Status"
              value={integ.status ?? '—'}
              status={statusOf(integ.status)}
            />
            {integ.manifest_entries !== undefined && (
              <StatusCard label="Manifest entries" value={integ.manifest_entries} />
            )}
            {integ.hash_mismatches !== undefined && (
              <StatusCard
                label="Hash mismatches"
                value={integ.hash_mismatches}
                status={integ.hash_mismatches === 0 ? 'ok' : 'error'}
              />
            )}
            {integ.freshness_days !== undefined && (
              <StatusCard
                label="Freshness"
                value={`${integ.freshness_days}d`}
                status={integ.stale ? 'warn' : 'ok'}
              />
            )}
          </div>

          {integ.reason && (
            <div className="text-sm text-gray-600 bg-gray-50 border border-gray-200 rounded-lg px-4 py-3">
              {integ.reason}
            </div>
          )}

          {integ.checks && Object.keys(integ.checks).length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                Checks
              </div>
              {Object.entries(integ.checks).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 last:border-0">
                  <span className="text-sm text-gray-700">{k.replace(/_/g, ' ')}</span>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${chipColor(v)}`}>
                    {v ? 'pass' : 'fail'}
                  </span>
                </div>
              ))}
            </div>
          )}

          <div className="text-xs text-gray-400 space-y-0.5">
            {integ.generated_at && <div>Generated: {new Date(integ.generated_at).toLocaleString()}</div>}
            {integ.artifact_path && <div className="font-mono">{integ.artifact_path}</div>}
          </div>
        </>
      )}
    </div>
  )
}
