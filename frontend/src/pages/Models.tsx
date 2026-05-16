import { useModels } from '../api/hooks'
import StatusCard from '../components/StatusCard'

type Provider = {
  name: string
  kind: string
  description?: string
  capabilities: string[]
  default_dimensions?: number
  max_dimensions?: number
  required_secrets?: string[]
  healthcheck?: string
  sdk_protocol?: string
}

type EmbeddingProfile = {
  provider: string
  model: string
  dimensions: number
  chunk_count: number
  status: string
}

function capBadge(cap: string) {
  const colors: Record<string, string> = {
    embed: 'text-teal-700 bg-teal-50',
    chat: 'text-violet-700 bg-violet-50',
    generate: 'text-blue-700 bg-blue-50',
    rerank: 'text-amber-700 bg-amber-50',
  }
  return colors[cap] ?? 'text-gray-600 bg-gray-100'
}

export default function Models() {
  const { data, isLoading } = useModels()

  const models = data as {
    embedding_profiles?: EmbeddingProfile[]
    registered_providers?: Provider[]
    registry_shell?: Record<string, { status: string; reason: string; providers: string[] }>
  } | undefined

  const profiles = models?.embedding_profiles ?? []
  const providers = models?.registered_providers ?? []

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Models</h1>
        <p className="text-gray-500 text-sm mt-0.5">Embedding models and rerankers</p>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : (
        <>
          {/* Registry shell */}
          {models?.registry_shell && (
            <div className="flex gap-3 flex-wrap">
              {Object.entries(models.registry_shell).map(([kind, info]) => (
                <StatusCard
                  key={kind}
                  label={kind}
                  value={info.providers.length}
                  sub={info.status}
                  status={info.status === 'ready' ? 'ok' : info.status === 'derived' ? 'neutral' : 'warn'}
                />
              ))}
            </div>
          )}

          {/* Active embedding profiles */}
          <div>
            <h2 className="text-sm font-semibold text-gray-700 mb-2">Active embedding profiles ({profiles.length})</h2>
            {profiles.length === 0 ? (
              <div className="text-sm text-gray-400">No embeddings indexed yet.</div>
            ) : (
              <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[1fr_1fr_auto_auto_auto] gap-4 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                  <div>Provider</div>
                  <div>Model</div>
                  <div className="text-right">Dims</div>
                  <div className="text-right">Chunks</div>
                  <div className="text-right">Status</div>
                </div>
                {profiles.map((p, i) => (
                  <div key={i} className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[1fr_1fr_auto_auto_auto] gap-4 items-center">
                    <div className="text-sm font-mono text-gray-800 truncate">{p.provider}</div>
                    <div className="text-sm font-mono text-gray-600 truncate">{p.model}</div>
                    <div className="text-sm text-gray-700 text-right">{p.dimensions}</div>
                    <div className="text-sm text-gray-700 text-right">{p.chunk_count}</div>
                    <div className="flex justify-end">
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded border text-emerald-700 bg-emerald-50 border-emerald-200">
                        {p.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Registered providers */}
          {providers.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-gray-700 mb-2">Registered providers ({providers.length})</h2>
              <div className="grid grid-cols-1 gap-3">
                {providers.map((p) => (
                  <div key={p.name} className="bg-white border border-gray-200 rounded-lg px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium text-gray-800">{p.name}</span>
                          <span className="text-[10px] font-mono text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">{p.kind}</span>
                        </div>
                        {p.description && <div className="text-xs text-gray-500 mt-0.5">{p.description}</div>}
                      </div>
                      <div className="flex gap-1 flex-wrap justify-end">
                        {p.capabilities.map((cap) => (
                          <span key={cap} className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${capBadge(cap)}`}>{cap}</span>
                        ))}
                      </div>
                    </div>
                    <div className="flex gap-4 mt-2 text-xs text-gray-500 flex-wrap">
                      {p.default_dimensions && <span>dims: {p.default_dimensions}{p.max_dimensions ? `–${p.max_dimensions}` : ''}</span>}
                      {p.sdk_protocol && <span className="font-mono">{p.sdk_protocol}</span>}
                      {p.required_secrets && p.required_secrets.length > 0 && (
                        <span className="text-amber-600">needs: {p.required_secrets.join(', ')}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
