import { useState } from 'react'
import { usePlugins } from '../api/hooks'

type Plugin = {
  plugin_id: string
  display_name: string
  description: string
  plugin_type: string
  family: string
  version: string
  tier: string
  status: string | { value: string }
  reason?: string
  capabilities: string[]
  configurable: boolean
  missing_dependencies: string[]
  secret_requirements: string[]
  docs_reference?: string
}

function statusColor(s: string) {
  const v = typeof s === 'string' ? s.toLowerCase() : ''
  if (v === 'ready') return 'text-emerald-700 bg-emerald-50 border-emerald-200'
  if (v === 'degraded') return 'text-amber-700 bg-amber-50 border-amber-200'
  return 'text-red-700 bg-red-50 border-red-200'
}

function statusStr(s: string | { value: string }): string {
  return typeof s === 'string' ? s : s.value
}

function capBadge(cap: string) {
  const colors: Record<string, string> = {
    ingest: 'text-blue-700 bg-blue-50',
    parse: 'text-teal-700 bg-teal-50',
    sink: 'text-violet-700 bg-violet-50',
    embed: 'text-teal-700 bg-teal-50',
  }
  return colors[cap] ?? 'text-gray-600 bg-gray-100'
}

export default function Plugins() {
  const { data: plugins, isLoading } = usePlugins()
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')

  const items = (plugins ?? []) as Plugin[]
  const types = ['all', ...new Set(items.map((p) => p.plugin_type))].sort()

  const filtered = items.filter((p) => {
    if (typeFilter !== 'all' && p.plugin_type !== typeFilter) return false
    if (search) {
      const q = search.toLowerCase()
      return (
        p.plugin_id.toLowerCase().includes(q) ||
        p.display_name.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q)
      )
    }
    return true
  })

  const ready = items.filter((p) => statusStr(p.status) === 'ready').length
  const degraded = items.filter((p) => statusStr(p.status) === 'degraded').length
  const unavailable = items.length - ready - degraded

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Plugins</h1>
        <p className="text-gray-500 text-sm mt-0.5">Source plugin registry</p>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : (
        <>
          <div className="flex gap-3 flex-wrap">
            {[
              { label: 'Ready', value: ready, status: 'ok' as const },
              { label: 'Degraded', value: degraded, status: 'warn' as const },
              { label: 'Unavailable', value: unavailable, status: unavailable > 0 ? 'error' as const : 'neutral' as const },
            ].map(({ label, value, status }) => (
              <div key={label} className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[90px]">
                <div className="text-[10px] font-bold uppercase text-gray-400">{label}</div>
                <div className={`text-base font-bold ${status === 'ok' ? 'text-emerald-600' : status === 'warn' ? 'text-amber-600' : status === 'error' ? 'text-red-500' : 'text-gray-400'}`}>{value}</div>
              </div>
            ))}
          </div>

          <div className="flex gap-3 flex-wrap items-center">
            <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
              {types.map((t) => (
                <button key={t} onClick={() => setTypeFilter(t)}
                  className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${typeFilter === t ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
                  {t}
                </button>
              ))}
            </div>
            <input type="text" placeholder="Search plugin…" value={search} onChange={(e) => setSearch(e.target.value)}
              className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 w-60" />
          </div>

          <div className="space-y-3">
            {filtered.length === 0 ? (
              <div className="text-sm text-gray-400 text-center py-6">No plugins match.</div>
            ) : filtered.map((p) => {
              const st = statusStr(p.status)
              return (
                <div key={p.plugin_id} className="bg-white border border-gray-200 rounded-lg px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-gray-800">{p.display_name}</span>
                        <span className="text-[10px] font-mono text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">{p.plugin_id}</span>
                        <span className="text-[10px] text-gray-400">v{p.version}</span>
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">{p.description}</div>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${statusColor(st)}`}>{st}</span>
                      <span className="text-[10px] text-gray-400">{p.tier}</span>
                    </div>
                  </div>

                  <div className="flex gap-3 mt-2 flex-wrap items-center">
                    <div className="flex gap-1">
                      {p.capabilities.map((cap) => (
                        <span key={cap} className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${capBadge(cap)}`}>{cap}</span>
                      ))}
                    </div>
                    {p.configurable && <span className="text-[10px] text-gray-400">configurable</span>}
                    {p.secret_requirements.length > 0 && (
                      <span className="text-[10px] text-amber-600">secrets: {p.secret_requirements.join(', ')}</span>
                    )}
                    {p.missing_dependencies.length > 0 && (
                      <span className="text-[10px] text-red-500">missing: {p.missing_dependencies.join(', ')}</span>
                    )}
                  </div>

                  {p.reason && (
                    <div className="text-xs text-amber-600 mt-1.5">{p.reason}</div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
