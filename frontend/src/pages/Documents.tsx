import { useState } from 'react'
import { useDocuments, useDocumentVersionChunks } from '../api/hooks'
import type { Document, Chunk } from '../api/types'

function uriLabel(uri: string): string {
  try {
    const parts = uri.split('/')
    return parts[parts.length - 1] || uri
  } catch {
    return uri
  }
}

function ChunkList({ versionId }: { versionId: string }) {
  const { data: chunks, isLoading } = useDocumentVersionChunks(versionId)

  if (isLoading)
    return <div className="p-3 text-gray-400 text-sm">Loading chunks…</div>
  if (!chunks?.length)
    return <div className="p-3 text-gray-400 text-sm">No chunks found.</div>

  return (
    <div className="max-h-80 overflow-y-auto divide-y divide-gray-100">
      {chunks.map((chunk: Chunk) => (
        <div key={chunk.id} className="px-4 py-2.5">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-bold text-gray-400">#{chunk.chunk_index}</span>
            {chunk.heading && (
              <span className="text-[11px] font-medium text-gray-600 truncate">{chunk.heading}</span>
            )}
            {chunk.page_number != null && (
              <span className="text-[10px] text-gray-400 ml-auto shrink-0">p.{chunk.page_number}</span>
            )}
          </div>
          <div className="text-xs text-gray-600 line-clamp-3 whitespace-pre-wrap">{chunk.text}</div>
        </div>
      ))}
    </div>
  )
}

function DocRow({ doc }: { doc: Document }) {
  const [expanded, setExpanded] = useState(false)
  const [tab, setTab] = useState<'preview' | 'chunks'>('preview')

  const v = doc.latest_version

  return (
    <div className="border-b border-gray-200 last:border-0">
      <button
        className="w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors flex items-start gap-3"
        onClick={() => setExpanded(!expanded)}
      >
        {/* URI / filename */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-gray-800 truncate max-w-xs" title={doc.uri}>
              {uriLabel(doc.uri)}
            </span>
            <span className="text-[10px] font-mono text-gray-400 truncate max-w-[200px]" title={doc.uri}>
              {doc.uri}
            </span>
          </div>
          <div className="flex gap-3 mt-1 text-xs text-gray-500 flex-wrap">
            <span className="font-medium text-gray-700">{doc.knowledge_base}</span>
            {doc.mime_type && <span>{doc.mime_type}</span>}
            <span>{v.parser_name}</span>
            <span>v{v.version_number}</span>
          </div>
        </div>

        {/* Chunk count */}
        <div className="shrink-0 text-right">
          <div className="text-sm font-bold text-gray-700">{v.chunk_count}</div>
          <div className="text-[10px] text-gray-400">chunks</div>
        </div>

        {/* Date */}
        <div className="shrink-0 text-right text-xs text-gray-400 whitespace-nowrap">
          <div>{new Date(v.created_at).toLocaleDateString()}</div>
          <div>{new Date(v.created_at).toLocaleTimeString()}</div>
        </div>

        <span className="shrink-0 text-gray-400 text-sm">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="border-t border-gray-200">
          {/* Tab bar */}
          <div className="flex border-b border-gray-100 bg-gray-50">
            {(['preview', 'chunks'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2 text-xs font-medium transition-colors ${
                  tab === t
                    ? 'text-brand border-b-2 border-brand bg-white'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {t === 'preview' ? 'Text preview' : `Chunks (${v.chunk_count})`}
              </button>
            ))}
          </div>

          {tab === 'preview' ? (
            <div className="px-4 py-3">
              {v.text_preview ? (
                <pre className="text-xs text-gray-600 whitespace-pre-wrap font-sans line-clamp-10 max-h-60 overflow-hidden">
                  {v.text_preview}
                </pre>
              ) : (
                <div className="text-gray-400 text-sm">No text preview available.</div>
              )}
            </div>
          ) : (
            <ChunkList versionId={v.id} />
          )}
        </div>
      )}
    </div>
  )
}

export default function Documents() {
  const { data: docs, isLoading } = useDocuments()
  const [kbFilter, setKbFilter] = useState('all')
  const [search, setSearch] = useState('')

  const kbs = [...new Set((docs ?? []).map((d) => d.knowledge_base))].sort()

  const filtered = (docs ?? []).filter((d) => {
    if (kbFilter !== 'all' && d.knowledge_base !== kbFilter) return false
    if (search) {
      const q = search.toLowerCase()
      return (
        d.uri.toLowerCase().includes(q) ||
        d.mime_type?.toLowerCase().includes(q) ||
        d.latest_version.parser_name?.toLowerCase().includes(q)
      )
    }
    return true
  })

  const totalChunks = filtered.reduce((s, d) => s + d.latest_version.chunk_count, 0)

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Documents</h1>
        <p className="text-gray-500 text-sm mt-0.5">Document version browser</p>
      </div>

      {/* Summary chips */}
      <div className="flex gap-3">
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[80px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Documents</div>
          <div className="text-base font-bold text-gray-700">{filtered.length}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[80px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Chunks</div>
          <div className="text-base font-bold text-gray-700">{totalChunks}</div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap items-center">
        {kbs.length > 1 && (
          <select
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
            value={kbFilter}
            onChange={(e) => setKbFilter(e.target.value)}
          >
            <option value="all">All KBs</option>
            {kbs.map((kb) => (
              <option key={kb} value={kb}>{kb}</option>
            ))}
          </select>
        )}
        <input
          type="text"
          placeholder="Search URI, MIME type, parser…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 w-72"
        />
      </div>

      {/* Document list */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-2 bg-gray-50 border-b border-gray-200">
          <div className="flex-1 text-[10px] font-bold uppercase tracking-wider text-gray-400">
            Document
          </div>
          <div className="shrink-0 w-16 text-right text-[10px] font-bold uppercase tracking-wider text-gray-400">
            Chunks
          </div>
          <div className="shrink-0 w-28 text-right text-[10px] font-bold uppercase tracking-wider text-gray-400">
            Indexed
          </div>
          <div className="w-4" />
        </div>

        {isLoading ? (
          <div className="p-6 text-gray-400 text-sm">Loading…</div>
        ) : !filtered.length ? (
          <div className="p-6 text-gray-400 text-sm text-center">
            {docs?.length ? 'No documents match.' : 'No documents indexed yet.'}
          </div>
        ) : (
          filtered.map((doc) => <DocRow key={doc.id} doc={doc} />)
        )}
      </div>
    </div>
  )
}
