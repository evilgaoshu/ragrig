import { useSources } from '../api/hooks'
import type { Source } from '../api/types'

function kindBadge(kind: string) {
  const map: Record<string, string> = {
    local_directory: 'bg-blue-100 text-blue-700',
    s3: 'bg-amber-100 text-amber-700',
    fileshare: 'bg-purple-100 text-purple-700',
    website: 'bg-teal-100 text-teal-700',
  }
  return map[kind] ?? 'bg-gray-100 text-gray-600'
}

function ConfigSummary({ config }: { config: Record<string, unknown> }) {
  const entries = Object.entries(config).filter(
    ([k]) => !['password', 'secret_key', 'access_key', 'private_key', 'api_key'].includes(k),
  )
  if (entries.length === 0) return <span className="text-gray-400">—</span>
  return (
    <div className="flex flex-wrap gap-1">
      {entries.slice(0, 4).map(([k, v]) => (
        <span key={k} className="text-[11px] bg-gray-100 rounded px-1 py-0.5 font-mono text-gray-600">
          {k}={String(v).slice(0, 24)}
        </span>
      ))}
      {entries.length > 4 && (
        <span className="text-[11px] text-gray-400">+{entries.length - 4} more</span>
      )}
    </div>
  )
}

export default function Sources() {
  const { data: sources, isLoading } = useSources()

  const byKB = (sources ?? []).reduce<Record<string, Source[]>>((acc, s) => {
    const kb = s.knowledge_base ?? '(none)'
    acc[kb] = [...(acc[kb] ?? []), s]
    return acc
  }, {})

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Sources</h1>
        <p className="text-gray-500 text-sm mt-0.5">
          Data source connectors attached to knowledge bases
        </p>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : !sources?.length ? (
        <div className="bg-white border border-gray-200 rounded-lg p-6 text-center">
          <p className="text-gray-400 text-sm">No sources configured.</p>
          <p className="text-gray-400 text-xs mt-1">
            Add sources via the{' '}
            <a href="/console" className="text-brand hover:underline">
              legacy console
            </a>{' '}
            or the API.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(byKB).sort().map(([kb, items]) => (
            <div key={kb}>
              <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-2">
                {kb}
              </h2>
              <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Kind</th>
                      <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">URI</th>
                      <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Config</th>
                      <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Added</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((s, i) => (
                      <tr key={s.id} className={`border-b border-gray-100 ${i % 2 === 0 ? '' : 'bg-gray-50'}`}>
                        <td className="px-4 py-2.5">
                          <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${kindBadge(s.kind)}`}>
                            {s.kind}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 font-mono text-xs text-gray-700 max-w-xs truncate">
                          {s.uri}
                        </td>
                        <td className="px-4 py-2.5">
                          <ConfigSummary config={s.config} />
                        </td>
                        <td className="px-4 py-2.5 text-gray-400 text-xs whitespace-nowrap">
                          {new Date(s.created_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
