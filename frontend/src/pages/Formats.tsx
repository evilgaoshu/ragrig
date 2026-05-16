import { useState } from 'react'
import { useSupportedFormats } from '../api/hooks'
import type { SupportedFormat } from '../api/types'

type StatusFilter = 'all' | 'supported' | 'preview' | 'planned'

function statusChip(status: SupportedFormat['status']) {
  switch (status) {
    case 'supported':
      return 'text-emerald-700 bg-emerald-50 border-emerald-200'
    case 'preview':
      return 'text-amber-700 bg-amber-50 border-amber-200'
    case 'planned':
      return 'text-gray-500 bg-gray-100 border-gray-200'
  }
}

function capabilityChip(cap: string) {
  switch (cap) {
    case 'parse':
      return 'text-blue-700 bg-blue-50'
    case 'chunk':
      return 'text-violet-700 bg-violet-50'
    case 'embed':
      return 'text-teal-700 bg-teal-50'
    default:
      return 'text-gray-600 bg-gray-100'
  }
}

function FormatRow({ fmt }: { fmt: SupportedFormat }) {
  return (
    <div className="flex items-start gap-4 px-4 py-3 border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors">
      {/* Extension */}
      <div className="shrink-0 w-20 pt-0.5">
        <span className="text-xs font-mono font-bold text-gray-800 bg-gray-100 px-2 py-0.5 rounded">
          {fmt.extension}
        </span>
      </div>

      {/* Name + parser */}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-gray-800">{fmt.display_name}</div>
        <div className="text-xs text-gray-400 mt-0.5 font-mono">{fmt.parser_id}</div>
        {fmt.limitations && (
          <div className="text-xs text-amber-600 mt-1">{fmt.limitations}</div>
        )}
        {fmt.fallback_policy && (
          <div className="text-xs text-gray-400 mt-0.5">
            Fallback: <span className="font-mono">{fmt.fallback_policy}</span>
          </div>
        )}
      </div>

      {/* Capabilities */}
      <div className="shrink-0 flex flex-wrap gap-1 justify-end pt-0.5">
        {fmt.capabilities.map((cap) => (
          <span
            key={cap}
            className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${capabilityChip(cap)}`}
          >
            {cap}
          </span>
        ))}
      </div>

      {/* Status + size */}
      <div className="shrink-0 flex flex-col items-end gap-1 pt-0.5">
        <span
          className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${statusChip(fmt.status)}`}
        >
          {fmt.status}
        </span>
        <span className="text-[10px] text-gray-400">{fmt.max_file_size_mb} MB max</span>
      </div>
    </div>
  )
}

export default function Formats() {
  const { data: formats, isLoading } = useSupportedFormats()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [search, setSearch] = useState('')

  const tabs: StatusFilter[] = ['all', 'supported', 'preview', 'planned']

  const filtered = (formats ?? []).filter((f) => {
    if (statusFilter !== 'all' && f.status !== statusFilter) return false
    if (search) {
      const q = search.toLowerCase()
      return (
        f.extension.includes(q) ||
        f.display_name.toLowerCase().includes(q) ||
        f.parser_id.toLowerCase().includes(q) ||
        f.mime_type.toLowerCase().includes(q)
      )
    }
    return true
  })

  const counts = {
    all: formats?.length ?? 0,
    supported: (formats ?? []).filter((f) => f.status === 'supported').length,
    preview: (formats ?? []).filter((f) => f.status === 'preview').length,
    planned: (formats ?? []).filter((f) => f.status === 'planned').length,
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Formats</h1>
        <p className="text-gray-500 text-sm mt-0.5">Supported file format registry</p>
      </div>

      {/* Summary chips */}
      <div className="flex gap-3">
        {(['supported', 'preview', 'planned'] as const).map((s) => (
          <div
            key={s}
            className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[80px]"
          >
            <div className="text-[10px] font-bold uppercase text-gray-400">{s}</div>
            <div
              className={`text-base font-bold ${
                s === 'supported'
                  ? 'text-emerald-600'
                  : s === 'preview'
                    ? 'text-amber-600'
                    : 'text-gray-400'
              }`}
            >
              {counts[s]}
            </div>
          </div>
        ))}
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          {tabs.map((t) => (
            <button
              key={t}
              onClick={() => setStatusFilter(t)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                statusFilter === t
                  ? 'bg-white shadow-sm text-gray-900'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t === 'all' ? `all (${counts.all})` : t}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Search extension, name, parser…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 w-64"
        />
      </div>

      {/* Table header */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="flex items-center gap-4 px-4 py-2 bg-gray-50 border-b border-gray-200">
          <div className="w-20 text-[10px] font-bold uppercase tracking-wider text-gray-400">Ext</div>
          <div className="flex-1 text-[10px] font-bold uppercase tracking-wider text-gray-400">
            Format / Parser
          </div>
          <div className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-gray-400">
            Capabilities
          </div>
          <div className="shrink-0 w-24 text-right text-[10px] font-bold uppercase tracking-wider text-gray-400">
            Status
          </div>
        </div>

        {isLoading ? (
          <div className="p-6 text-gray-400 text-sm">Loading…</div>
        ) : !filtered.length ? (
          <div className="p-6 text-gray-400 text-sm text-center">
            {formats?.length ? 'No formats match.' : 'No formats registered.'}
          </div>
        ) : (
          filtered.map((fmt) => <FormatRow key={fmt.extension} fmt={fmt} />)
        )}
      </div>
    </div>
  )
}
