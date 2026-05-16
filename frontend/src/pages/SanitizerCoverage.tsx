import { useSanitizerCoverage } from '../api/hooks'
import StatusCard from '../components/StatusCard'

function statusOf(s: string): 'ok' | 'warn' | 'error' | 'neutral' {
  if (s === 'ok' || s === 'healthy') return 'ok'
  if (s === 'degraded') return 'warn'
  if (s === 'failure' || s === 'failed') return 'error'
  return 'neutral'
}

export default function SanitizerCoverage() {
  const { data, isLoading } = useSanitizerCoverage()

  const coverage = data as {
    parsers: { parser_id: string; fixtures: number; redacted: number; degraded: number; golden_hash: string; status: string; degraded_reason?: string }[]
    totals: { fixtures: number; redacted: number; degraded: number }
    redaction_floor: number
    redaction_floor_check: boolean
  } | null | undefined

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Sanitizer Coverage</h1>
        <p className="text-gray-500 text-sm mt-0.5">Parser redaction coverage metrics from golden snapshots</p>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : !coverage ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center">
          <div className="text-sm font-medium text-gray-500">No golden snapshots found</div>
          <div className="text-xs text-gray-400 mt-1">Run the sanitizer test suite to generate coverage data.</div>
        </div>
      ) : (
        <>
          <div className="flex gap-3 flex-wrap">
            <StatusCard label="Parsers" value={coverage.totals.fixtures} />
            <StatusCard label="Redacted" value={coverage.totals.redacted} status={coverage.totals.redacted > 0 ? 'ok' : 'error'} />
            <StatusCard label="Degraded" value={coverage.totals.degraded} status={coverage.totals.degraded === 0 ? 'ok' : 'warn'} />
            <StatusCard
              label="Floor check"
              value={coverage.redaction_floor_check ? 'pass' : 'fail'}
              status={coverage.redaction_floor_check ? 'ok' : 'error'}
              sub={`≥${coverage.redaction_floor} per parser`}
            />
          </div>

          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 text-[10px] font-bold uppercase tracking-wider text-gray-400">
              <div>Parser</div>
              <div className="text-right">Redacted</div>
              <div className="text-right">Degraded</div>
              <div className="text-right">Hash</div>
              <div className="text-right">Status</div>
            </div>
            {coverage.parsers.map((p) => (
              <div key={p.parser_id} className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 items-start">
                <div>
                  <div className="text-sm font-mono text-gray-800">{p.parser_id}</div>
                  {p.degraded_reason && (
                    <div className="text-xs text-amber-600 mt-0.5">{p.degraded_reason}</div>
                  )}
                </div>
                <div className="text-sm text-gray-700 text-right">{p.redacted}</div>
                <div className={`text-sm text-right ${p.degraded > 0 ? 'text-amber-600 font-medium' : 'text-gray-400'}`}>{p.degraded}</div>
                <div className="text-xs font-mono text-gray-400 text-right">{p.golden_hash}</div>
                <div className="flex justify-end">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${
                    statusOf(p.status) === 'ok' ? 'text-emerald-700 bg-emerald-50 border-emerald-200' :
                    statusOf(p.status) === 'warn' ? 'text-amber-700 bg-amber-50 border-amber-200' :
                    'text-red-700 bg-red-50 border-red-200'
                  }`}>{p.status}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
