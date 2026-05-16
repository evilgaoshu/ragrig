import { useSanitizerDriftSummary, useSanitizerDriftHistory } from '../api/hooks'
import StatusCard from '../components/StatusCard'

function riskColor(risk: string) {
  if (risk === 'high') return 'text-red-600 bg-red-50 border-red-200'
  if (risk === 'medium') return 'text-amber-600 bg-amber-50 border-amber-200'
  if (risk === 'low' || risk === 'none') return 'text-emerald-600 bg-emerald-50 border-emerald-200'
  return 'text-gray-500 bg-gray-100 border-gray-200'
}

export default function SanitizerDrift() {
  const { data: summary, isLoading: summaryLoading } = useSanitizerDriftSummary()
  const { data: history, isLoading: historyLoading } = useSanitizerDriftHistory()

  const sum = summary as {
    available?: boolean
    status?: string
    risk?: string
    latest_report?: string
    degraded_report_count?: number
    total_reports?: number
    latest_generated_at?: string
    reason?: string
  } | undefined

  const hist = history as {
    available?: boolean
    status?: string
    reason?: string
    reports?: {
      report_id: string
      risk: string
      changed_parser_count: number
      base_commit?: string
      head_commit?: string
      generated_at?: string
    }[]
  } | undefined

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Sanitizer Drift</h1>
        <p className="text-gray-500 text-sm mt-0.5">Sanitizer drift history and trend</p>
      </div>

      {summaryLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : sum?.available === false ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center">
          <div className="text-sm font-medium text-gray-500">No drift history available</div>
          {sum.reason && <div className="text-xs text-gray-400 mt-1">{sum.reason}</div>}
        </div>
      ) : (
        <>
          <div className="flex gap-3 flex-wrap">
            <StatusCard label="Reports" value={sum?.total_reports ?? '—'} />
            <StatusCard
              label="Degraded"
              value={sum?.degraded_report_count ?? '—'}
              status={(sum?.degraded_report_count ?? 0) === 0 ? 'ok' : 'warn'}
            />
            {sum?.risk && (
              <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[90px]">
                <div className="text-[10px] font-bold uppercase text-gray-400">Risk</div>
                <span className={`text-xs font-bold px-1.5 py-0.5 rounded border ${riskColor(sum.risk)}`}>
                  {sum.risk}
                </span>
              </div>
            )}
          </div>

          {!historyLoading && hist?.reports && hist.reports.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[auto_auto_1fr_auto] gap-4 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                <div>Risk</div>
                <div>Changed</div>
                <div>Report</div>
                <div className="text-right">Generated</div>
              </div>
              {hist.reports.map((r) => (
                <div key={r.report_id} className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[auto_auto_1fr_auto] gap-4 items-center">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${riskColor(r.risk)}`}>{r.risk}</span>
                  <div className="text-sm text-gray-700">{r.changed_parser_count} parsers</div>
                  <div className="text-xs font-mono text-gray-500 truncate">{r.report_id}</div>
                  <div className="text-xs text-gray-400 text-right whitespace-nowrap">
                    {r.generated_at ? new Date(r.generated_at).toLocaleDateString() : '—'}
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
