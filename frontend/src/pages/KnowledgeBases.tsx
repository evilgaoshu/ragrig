import { useState } from 'react'
import { useKnowledgeBases, useCreateKnowledgeBase } from '../api/hooks'

export default function KnowledgeBases() {
  const { data: kbs, isLoading } = useKnowledgeBases()
  const create = useCreateKnowledgeBase()
  const [name, setName] = useState('')
  const [error, setError] = useState('')

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!name.trim()) return
    try {
      await create.mutateAsync(name.trim())
      setName('')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create')
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Knowledge Bases</h1>
        <p className="text-gray-500 text-sm mt-0.5">Manage knowledge base inventory</p>
      </div>

      {/* Create form */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Create Knowledge Base</h2>
        <form onSubmit={handleCreate} className="flex gap-2 items-start">
          <div className="flex-1">
            <input
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand"
              placeholder="knowledge-base-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
          </div>
          <button
            type="submit"
            disabled={create.isPending || !name.trim()}
            className="px-3 py-1.5 bg-brand text-white rounded text-sm font-medium hover:bg-brand/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
        </form>
      </div>

      {/* List */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-4 text-gray-400 text-sm">Loading…</div>
        ) : !kbs?.length ? (
          <div className="p-4 text-gray-400 text-sm">No knowledge bases yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Name</th>
                <th className="text-right px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Docs</th>
                <th className="text-right px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Chunks</th>
                <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Model</th>
                <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Created</th>
              </tr>
            </thead>
            <tbody>
              {kbs.map((kb, i) => (
                <tr key={kb.id} className={`border-b border-gray-100 ${i % 2 === 0 ? '' : 'bg-gray-50'}`}>
                  <td className="px-4 py-2.5 font-medium text-brand">{kb.name}</td>
                  <td className="px-4 py-2.5 text-right text-gray-600">{kb.document_count ?? 0}</td>
                  <td className="px-4 py-2.5 text-right text-gray-600">{kb.chunk_count ?? 0}</td>
                  <td className="px-4 py-2.5 text-gray-500">{kb.embedding_model ?? '—'}</td>
                  <td className="px-4 py-2.5 text-gray-400 text-xs">
                    {new Date(kb.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
