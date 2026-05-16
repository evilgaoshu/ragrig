import { useState } from 'react'
import { useProcessingProfileMatrix } from '../api/hooks'

type Cell = {
  profile_id: string
  extension: string
  task_type: string
  display_name: string
  provider: string
  model_id?: string
  status: string
  kind: string
  source: string
  is_default: boolean
  provider_available: boolean
}

type MatrixData = {
  extensions: string[]
  task_types: string[]
  cells: Record<string, Cell>
}

function kindColor(kind: string) {
  if (kind === 'deterministic') return 'text-blue-700 bg-blue-50'
  if (kind === 'llm-assisted' || kind === 'LLM-assisted') return 'text-violet-700 bg-violet-50'
  return 'text-gray-600 bg-gray-100'
}

function availableColor(ok: boolean) {
  return ok ? 'text-emerald-600' : 'text-red-500'
}

export default function ProfileMatrix() {
  const { data, isLoading } = useProcessingProfileMatrix()
  const [selectedExt, setSelectedExt] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const matrix = data as MatrixData | undefined

  if (isLoading) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-bold text-gray-900 mb-4">Profile Matrix</h1>
        <div className="text-gray-400 text-sm">Loading…</div>
      </div>
    )
  }

  if (!matrix) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-bold text-gray-900 mb-4">Profile Matrix</h1>
        <div className="text-sm text-gray-400">No matrix data available.</div>
      </div>
    )
  }

  const extensions = matrix.extensions ?? []
  const taskTypes = matrix.task_types ?? []
  const cells = matrix.cells ?? {}

  const filteredExts = extensions.filter((ext) => {
    if (selectedExt && ext !== selectedExt) return false
    if (search) return ext.toLowerCase().includes(search.toLowerCase())
    return true
  })

  const overrideCount = Object.values(cells).filter((c) => !c.is_default).length
  const unavailableCount = Object.values(cells).filter((c) => !c.provider_available).length

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Profile Matrix</h1>
        <p className="text-gray-500 text-sm mt-0.5">Processing profile override matrix</p>
      </div>

      <div className="flex gap-3 flex-wrap">
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[90px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Extensions</div>
          <div className="text-base font-bold text-gray-700">{extensions.length}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[90px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Overrides</div>
          <div className={`text-base font-bold ${overrideCount > 0 ? 'text-violet-600' : 'text-gray-400'}`}>{overrideCount}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[90px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Unavailable</div>
          <div className={`text-base font-bold ${unavailableCount > 0 ? 'text-red-500' : 'text-gray-400'}`}>{unavailableCount}</div>
        </div>
      </div>

      <div className="flex gap-3 flex-wrap items-center">
        <input type="text" placeholder="Filter extension…" value={search} onChange={(e) => setSearch(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 w-48" />
        {selectedExt && (
          <button onClick={() => setSelectedExt(null)} className="text-xs text-brand hover:underline">
            Clear filter
          </button>
        )}
      </div>

      {/* Matrix table */}
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs border border-gray-200 rounded-lg overflow-hidden bg-white">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider text-gray-400 sticky left-0 bg-gray-50">
                Extension
              </th>
              {taskTypes.map((tt) => (
                <th key={tt} className="px-3 py-2 text-center text-[10px] font-bold uppercase tracking-wider text-gray-400 whitespace-nowrap">
                  {tt}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredExts.map((ext) => (
              <tr key={ext} className="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors">
                <td className="px-3 py-2 sticky left-0 bg-white font-mono text-gray-700 font-medium">
                  <button onClick={() => setSelectedExt(ext === selectedExt ? null : ext)} className="hover:text-brand">
                    {ext}
                  </button>
                </td>
                {taskTypes.map((tt) => {
                  const cell = cells[`${ext}.${tt}`]
                  if (!cell) return <td key={tt} className="px-3 py-2 text-center text-gray-300">—</td>
                  return (
                    <td key={tt} className="px-3 py-2 text-center">
                      <div className="flex flex-col items-center gap-0.5">
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${kindColor(cell.kind)}`}>
                          {cell.kind === 'deterministic' ? 'det' : 'llm'}
                        </span>
                        <span className="text-[10px] font-mono text-gray-500 truncate max-w-[80px]" title={cell.provider}>
                          {cell.provider}
                        </span>
                        <span className={`text-[9px] ${availableColor(cell.provider_available)}`}>
                          {cell.is_default ? 'default' : 'override'}
                        </span>
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
