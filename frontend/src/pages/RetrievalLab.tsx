import { useState } from 'react'
import { useRetrieval, useKnowledgeBases } from '../api/hooks'
import type { RetrievalResult } from '../api/types'

export default function RetrievalLab() {
  const { data: kbs } = useKnowledgeBases()
  const search = useRetrieval()

  const [kb, setKb] = useState('')
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [mode, setMode] = useState('dense')

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    if (!kb || !query.trim()) return
    search.mutate({ knowledge_base: kb, query: query.trim(), top_k: topK, provider: 'deterministic-local', model: null, mode })
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Retrieval Lab</h1>
        <p className="text-gray-500 text-sm mt-0.5">Test hybrid retrieval with rank stage trace</p>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
        <form onSubmit={handleSearch} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Knowledge Base</span>
              <select
                className="mt-1 w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40"
                value={kb}
                onChange={(e) => setKb(e.target.value)}
              >
                <option value="">Select…</option>
                {kbs?.map((k) => <option key={k.id} value={k.name}>{k.name}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Mode</span>
              <select
                className="mt-1 w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40"
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                <option value="dense">dense</option>
                <option value="hybrid">hybrid</option>
                <option value="rerank">rerank</option>
                <option value="hybrid_rerank">hybrid + rerank</option>
              </select>
            </label>
          </div>
          <label className="block">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Query</span>
            <input
              className="mt-1 w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40"
              placeholder="What does this knowledge base say?"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-gray-600">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Top K</span>
              <input
                type="number"
                min={1}
                max={50}
                className="w-16 border border-gray-300 rounded px-2 py-1 text-sm"
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
              />
            </label>
            <button
              type="submit"
              disabled={search.isPending || !kb || !query.trim()}
              className="ml-auto px-4 py-1.5 bg-brand text-white rounded text-sm font-medium hover:bg-brand/90 disabled:opacity-50 transition-colors"
            >
              {search.isPending ? 'Searching…' : 'Search'}
            </button>
          </div>
        </form>
      </div>

      {search.error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-600">
          {search.error instanceof Error ? search.error.message : 'Search failed'}
        </div>
      )}

      {search.data && (
        <div className="space-y-3">
          <div className="text-sm text-gray-500">
            {search.data.total_results} result{search.data.total_results !== 1 ? 's' : ''} · {search.data.provider} / {search.data.model || '—'}
          </div>
          {search.data.results.map((r: RetrievalResult, i: number) => (
            <div key={r.chunk_id} className="bg-white border border-gray-200 rounded-lg p-4 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-bold text-gray-400">#{i + 1}</span>
                <span className="text-xs text-gray-400 truncate flex-1">{r.document_uri}</span>
                <span className="text-xs font-mono bg-gray-100 px-1.5 py-0.5 rounded text-gray-600">
                  score {r.score?.toFixed(4) ?? '—'}
                </span>
              </div>
              <p className="text-sm text-gray-800 leading-relaxed">{r.text_preview}</p>
              {Boolean(r.rank_stage_trace) && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-gray-400 hover:text-gray-600">rank_stage_trace</summary>
                  <pre className="mt-1 bg-gray-50 p-2 rounded overflow-x-auto text-gray-600">
                    {JSON.stringify(r.rank_stage_trace as object, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
