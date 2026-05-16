import { useOpsDiagnostics } from '../api/hooks'
import StatusCard from '../components/StatusCard'

function statusOf(s: string | undefined): 'ok' | 'warn' | 'error' | 'neutral' {
  if (!s) return 'neutral'
  if (s === 'success' || s === 'ok') return 'ok'
  if (s === 'degraded') return 'warn'
  return 'error'
}

function chipColor(s: 'ok' | 'warn' | 'error' | 'neutral') {
  if (s === 'ok') return 'text-emerald-700 bg-emerald-50 border-emerald-200'
  if (s === 'warn') return 'text-amber-700 bg-amber-50 border-amber-200'
  if (s === 'error') return 'text-red-700 bg-red-50 border-red-200'
  return 'text-gray-500 bg-gray-100 border-gray-200'
}

const OP_LABELS: Record<string, string> = {
  'ops-deploy-summary': 'Deploy',
  'ops-backup-summary': 'Backup',
  'ops-restore-summary': 'Restore',
  'ops-upgrade-summary': 'Upgrade',
}

export default function OpsDiagnostics() {
  const { data, isLoading } = useOpsDiagnostics()

  const diag = data as {
    overall_status?: string
    artifacts_dir?: string
    summaries?: Record<string, {
      available: boolean
      artifact?: string
      status?: string
      version?: string
      snapshot_id?: string
      schema_revision?: string
      generated_at?: string
      check_count?: number
      reason?: string
    }>
  } | undefined

  const summaries = diag?.summaries ? Object.entries(diag.summaries) : []

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Ops Diagnostics</h1>
        <p className="text-gray-500 text-sm mt-0.5">Deploy, backup, and restore diagnostics</p>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : !diag ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center">
          <div className="text-sm text-gray-500">No diagnostics data available</div>
        </div>
      ) : (
        <>
          <div className="flex gap-3 flex-wrap">
            <StatusCard
              label="Overall"
              value={diag.overall_status ?? '—'}
              status={statusOf(diag.overall_status)}
            />
            <StatusCard
              label="Artifacts"
              value={summaries.filter(([, s]) => s.available).length}
              sub={`of ${summaries.length}`}
              status={summaries.every(([, s]) => s.available) ? 'ok' : 'warn'}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {summaries.map(([key, s]) => {
              const st = statusOf(s.status)
              return (
                <div key={key} className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                  <div className={`px-4 py-2 border-b flex items-center justify-between ${
                    st === 'ok' ? 'bg-emerald-50 border-emerald-100' :
                    st === 'warn' ? 'bg-amber-50 border-amber-100' :
                    st === 'error' ? 'bg-red-50 border-red-100' :
                    'bg-gray-50 border-gray-200'
                  }`}>
                    <span className="text-sm font-semibold text-gray-800">
                      {OP_LABELS[key] ?? key}
                    </span>
                    {s.status && (
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${chipColor(st)}`}>
                        {s.status}
                      </span>
                    )}
                  </div>
                  <div className="px-4 py-3 space-y-1.5 text-xs text-gray-600">
                    {!s.available ? (
                      <div className="text-amber-600">{s.reason ?? 'Artifact not found'}</div>
                    ) : (
                      <>
                        {s.version && <div><span className="text-gray-400">Version</span> {s.version}</div>}
                        {s.schema_revision && <div><span className="text-gray-400">Schema</span> {s.schema_revision}</div>}
                        {s.snapshot_id && <div><span className="text-gray-400">Snapshot</span> <span className="font-mono">{s.snapshot_id}</span></div>}
                        {s.check_count !== undefined && <div><span className="text-gray-400">Checks</span> {s.check_count}</div>}
                        {s.generated_at && <div className="text-gray-400">{new Date(s.generated_at).toLocaleString()}</div>}
                      </>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
