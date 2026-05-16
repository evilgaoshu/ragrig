import { useEvaluationRuns, useEvaluationBaselines } from '../api/hooks'
import StatusCard from '../components/StatusCard'

type EvalRun = {
  run_id: string
  knowledge_base?: string
  golden_path?: string
  status?: string
  score?: number
  total_questions?: number
  passed?: number
  failed?: number
  created_at?: string
  provider?: string
  model?: string
}

type Baseline = {
  baseline_id: string
  run_id: string
  created_at?: string
  label?: string
  is_current?: boolean
}

function statusChip(s: string | undefined) {
  if (!s) return 'text-gray-500 bg-gray-100 border-gray-200'
  const l = s.toLowerCase()
  if (l === 'pass' || l === 'passed') return 'text-emerald-700 bg-emerald-50 border-emerald-200'
  if (l === 'fail' || l === 'failed') return 'text-red-700 bg-red-50 border-red-200'
  return 'text-amber-700 bg-amber-50 border-amber-200'
}

export default function Evaluation() {
  const { data: runsData, isLoading: runsLoading } = useEvaluationRuns()
  const { data: baselinesData, isLoading: baselinesLoading } = useEvaluationBaselines()

  const runs = ((runsData as { runs?: EvalRun[] })?.runs ?? []) as EvalRun[]
  const baselines = ((baselinesData as { baselines?: Baseline[] })?.baselines ?? []) as Baseline[]
  const currentBaselineId = (baselinesData as { current_baseline_id?: string })?.current_baseline_id

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Evaluation</h1>
        <p className="text-gray-500 text-sm mt-0.5">RAG evaluation runs and baselines</p>
      </div>

      {/* Summary */}
      {!runsLoading && (
        <div className="flex gap-3 flex-wrap">
          <StatusCard label="Runs" value={runs.length} />
          <StatusCard label="Baselines" value={baselines.length} />
          {runs.length > 0 && (
            <StatusCard
              label="Avg score"
              value={runs.some((r) => r.score !== undefined)
                ? `${(runs.filter(r => r.score !== undefined).reduce((s, r) => s + (r.score ?? 0), 0) / runs.filter(r => r.score !== undefined).length * 100).toFixed(1)}%`
                : '—'}
            />
          )}
        </div>
      )}

      {/* Baselines */}
      {!baselinesLoading && baselines.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Baselines</h2>
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            {baselines.map((b) => (
              <div key={b.baseline_id} className="flex items-center gap-4 px-4 py-2.5 border-b border-gray-100 last:border-0">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-gray-700 truncate">{b.baseline_id}</span>
                    {b.is_current || b.baseline_id === currentBaselineId ? (
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded border text-emerald-700 bg-emerald-50 border-emerald-200">current</span>
                    ) : null}
                  </div>
                  {b.label && <div className="text-xs text-gray-500">{b.label}</div>}
                </div>
                {b.created_at && (
                  <div className="text-xs text-gray-400 whitespace-nowrap shrink-0">
                    {new Date(b.created_at).toLocaleDateString()}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Runs */}
      <div>
        <h2 className="text-sm font-semibold text-gray-700 mb-2">Runs</h2>
        {runsLoading ? (
          <div className="text-gray-400 text-sm">Loading…</div>
        ) : runs.length === 0 ? (
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center">
            <div className="text-sm text-gray-500">No evaluation runs yet.</div>
            <div className="text-xs text-gray-400 mt-1">Use the API to run a golden question evaluation.</div>
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 text-[10px] font-bold uppercase tracking-wider text-gray-400">
              <div>Run</div>
              <div className="text-right">Questions</div>
              <div className="text-right">Score</div>
              <div className="text-right">Status</div>
              <div className="text-right">Date</div>
            </div>
            {runs.map((r) => (
              <div key={r.run_id} className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 items-start">
                <div>
                  <div className="text-xs font-mono text-gray-700 truncate">{r.run_id}</div>
                  {r.knowledge_base && <div className="text-xs text-gray-500">{r.knowledge_base}</div>}
                  {(r.provider || r.model) && (
                    <div className="text-xs text-gray-400">{r.provider} {r.model}</div>
                  )}
                </div>
                <div className="text-sm text-gray-700 text-right">{r.total_questions ?? '—'}</div>
                <div className="text-sm text-gray-700 text-right">
                  {r.score !== undefined ? `${(r.score * 100).toFixed(1)}%` : '—'}
                </div>
                <div className="flex justify-end">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${statusChip(r.status)}`}>
                    {r.status ?? '—'}
                  </span>
                </div>
                <div className="text-xs text-gray-400 text-right whitespace-nowrap">
                  {r.created_at ? new Date(r.created_at).toLocaleDateString() : '—'}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
