import StatusCard from '../components/StatusCard'
import { useSystemStatus, useKnowledgeBases, usePipelineRuns } from '../api/hooks'

function deriveStatus(val: string | undefined): 'ok' | 'error' | 'warn' | 'neutral' {
  if (!val) return 'neutral'
  const v = val.toLowerCase()
  if (v === 'ok' || v === 'connected' || v === 'healthy') return 'ok'
  if (v === 'error' || v === 'unhealthy') return 'error'
  if (v === 'degraded') return 'warn'
  return 'neutral'
}

export default function Overview() {
  const { data: status, isLoading } = useSystemStatus()
  const { data: kbs } = useKnowledgeBases()
  const { data: runs } = usePipelineRuns()

  if (isLoading) {
    return (
      <div className="p-6 text-gray-400 text-sm">Loading system status…</div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Overview</h1>
        <p className="text-gray-500 text-sm mt-0.5">
          Operator dashboard — knowledge bases, ingestion, and system state
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        <StatusCard
          label="API"
          value={status?.api ?? '—'}
          sub={`v${status?.api_version ?? '?'}`}
          status={deriveStatus(status?.api)}
        />
        <StatusCard
          label="Database"
          value={status?.database ?? '—'}
          sub={status?.database_detail ?? undefined}
          status={deriveStatus(status?.database)}
        />
        <StatusCard
          label="Vector Backend"
          value={status?.vector ?? '—'}
          sub={status?.vector_detail ?? undefined}
          status={deriveStatus(status?.vector)}
        />
        <StatusCard
          label="Knowledge Bases"
          value={kbs?.length ?? status?.knowledge_bases ?? 0}
          sub="Knowledge inventory"
          status="neutral"
        />
        <StatusCard
          label="Pipeline Runs"
          value={runs?.length ?? status?.recent_pipeline_runs ?? 0}
          sub="Recent ingestion"
          status="neutral"
        />
        <StatusCard
          label="Embedding Profiles"
          value={status?.embedding_profiles ?? 0}
          sub="Real indexed profiles"
          status="neutral"
        />
      </div>

      {kbs && kbs.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Knowledge Bases</h2>
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Name</th>
                  <th className="text-right px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Docs</th>
                  <th className="text-right px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Chunks</th>
                  <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Model</th>
                </tr>
              </thead>
              <tbody>
                {kbs.map((kb, i) => (
                  <tr key={kb.id} className={i % 2 === 0 ? '' : 'bg-gray-50'}>
                    <td className="px-4 py-2 font-medium text-brand">{kb.name}</td>
                    <td className="px-4 py-2 text-right text-gray-600">{kb.document_count ?? 0}</td>
                    <td className="px-4 py-2 text-right text-gray-600">{kb.chunk_count ?? 0}</td>
                    <td className="px-4 py-2 text-gray-500">{kb.embedding_model ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
