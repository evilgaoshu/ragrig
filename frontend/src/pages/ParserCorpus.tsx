import { useAdvancedParserCorpus } from '../api/hooks'
import StatusCard from '../components/StatusCard'

function statusOf(s: string | undefined): 'ok' | 'warn' | 'error' | 'neutral' {
  if (!s) return 'neutral'
  if (s === 'healthy' || s === 'ok' || s === 'pass') return 'ok'
  if (s === 'degraded' || s === 'skipped') return 'warn'
  return 'error'
}

function chipColor(s: string) {
  const c = statusOf(s)
  if (c === 'ok') return 'text-emerald-700 bg-emerald-50 border-emerald-200'
  if (c === 'warn') return 'text-amber-700 bg-amber-50 border-amber-200'
  if (c === 'error') return 'text-red-700 bg-red-50 border-red-200'
  return 'text-gray-500 bg-gray-100 border-gray-200'
}

export default function ParserCorpus() {
  const { data, isLoading } = useAdvancedParserCorpus()

  const corpus = data as {
    available?: boolean
    status?: string
    total_fixtures?: number
    healthy?: number
    degraded?: number
    skipped?: number
    failed?: number
    report_path?: string
    generated_at?: string
    reason?: string
    results?: { format: string; fixture_id: string; parser: string; status: string; degraded_reason?: string }[]
  } | undefined

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Parser Corpus</h1>
        <p className="text-gray-500 text-sm mt-0.5">Advanced parser corpus status</p>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : corpus?.available === false ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center space-y-1">
          <div className="text-sm font-medium text-gray-500">No parser corpus artifact found</div>
          {corpus.reason && <div className="text-xs text-gray-400">{corpus.reason}</div>}
        </div>
      ) : corpus ? (
        <>
          <div className="flex gap-3 flex-wrap">
            <StatusCard label="Status" value={corpus.status ?? '—'} status={statusOf(corpus.status)} />
            <StatusCard label="Total" value={corpus.total_fixtures ?? '—'} />
            <StatusCard label="Healthy" value={corpus.healthy ?? '—'} status={(corpus.healthy ?? 0) > 0 ? 'ok' : 'neutral'} />
            <StatusCard label="Degraded" value={corpus.degraded ?? '—'} status={(corpus.degraded ?? 0) === 0 ? 'ok' : 'warn'} />
            <StatusCard label="Skipped" value={corpus.skipped ?? '—'} />
            <StatusCard label="Failed" value={corpus.failed ?? '—'} status={(corpus.failed ?? 0) === 0 ? 'ok' : 'error'} />
          </div>

          {corpus.results && corpus.results.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[auto_1fr_1fr_auto] gap-4 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                <div>Status</div>
                <div>Fixture</div>
                <div>Parser</div>
                <div>Format</div>
              </div>
              {corpus.results.map((r) => (
                <div key={r.fixture_id} className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[auto_1fr_1fr_auto] gap-4 items-start">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${chipColor(r.status)}`}>{r.status}</span>
                  <div>
                    <div className="text-xs font-mono text-gray-700 truncate">{r.fixture_id}</div>
                    {r.degraded_reason && <div className="text-xs text-amber-600 mt-0.5">{r.degraded_reason}</div>}
                  </div>
                  <div className="text-xs text-gray-600 truncate">{r.parser}</div>
                  <div className="text-xs font-mono text-gray-400">{r.format}</div>
                </div>
              ))}
            </div>
          )}

          <div className="text-xs text-gray-400 space-y-0.5">
            {corpus.generated_at && <div>Generated: {new Date(corpus.generated_at).toLocaleString()}</div>}
            {corpus.report_path && <div className="font-mono">{corpus.report_path}</div>}
          </div>
        </>
      ) : null}
    </div>
  )
}
