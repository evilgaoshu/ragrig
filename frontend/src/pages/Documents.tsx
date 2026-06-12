import { useState } from 'react'
import {
  useChunkPreview,
  useChunkReview,
  useDocuments,
  useReindexChunkOverride,
  useResetChunkOverride,
  useSaveChunkOverride,
} from '../api/hooks'
import type { Document, Chunk, ChunkReview } from '../api/types'

function uriLabel(uri: string): string {
  try {
    const parts = uri.split('/')
    return parts[parts.length - 1] || uri
  } catch {
    return uri
  }
}

function ChunkList({ versionId }: { versionId: string }) {
  const { data: review, isLoading } = useChunkReview(versionId)

  if (isLoading)
    return <div className="p-3 text-gray-400 text-sm">Loading chunks…</div>
  if (!review?.items.length)
    return <div className="p-3 text-gray-400 text-sm">No chunks found.</div>

  const revision = String(review.override?.revision ?? 'none')
  const itemKey = review.items.map((chunk) => chunk.id).join(':')
  return (
    <ChunkEditor
      key={`${review.index_status.status}:${revision}:${itemKey}`}
      versionId={versionId}
      review={review}
    />
  )
}

function ChunkEditor({ versionId, review }: { versionId: string; review: ChunkReview }) {
  const preview = useChunkPreview()
  const saveOverride = useSaveChunkOverride(versionId)
  const resetOverride = useResetChunkOverride(versionId)
  const reindex = useReindexChunkOverride(versionId)
  const [chunks, setChunks] = useState<Chunk[]>(review.items)
  const [operations, setOperations] = useState<Array<Record<string, unknown>>>([])
  const [reason, setReason] = useState('Manual chunk review')
  const [resetPending, setResetPending] = useState(false)

  const pending = operations.length > 0 || resetPending
  const metadataString = (chunk: Chunk, key: string) =>
    typeof chunk.metadata[key] === 'string' ? String(chunk.metadata[key]) : ''

  const splitChunk = (index: number) => {
    const chunk = chunks[index]
    const offset = Math.floor(chunk.text.length / 2)
    const splitAt = Math.min(chunk.char_end - 1, chunk.char_start + Math.max(offset, 1))
    if (splitAt <= chunk.char_start || splitAt >= chunk.char_end) return
    const textOffset = splitAt - chunk.char_start
    const baseMetadata = { ...chunk.metadata, split_reason: 'manual_split' }
    const next = [
      ...chunks.slice(0, index),
      {
        ...chunk,
        id: `${chunk.id}-left`,
        text: chunk.text.slice(0, textOffset),
        char_end: splitAt,
        metadata: baseMetadata,
      },
      {
        ...chunk,
        id: `${chunk.id}-right`,
        text: chunk.text.slice(textOffset),
        char_start: splitAt,
        metadata: baseMetadata,
      },
      ...chunks.slice(index + 1),
    ]
    setChunks(next.map((item, chunkIndex) => ({ ...item, chunk_index: chunkIndex })))
    setOperations((items) => [
      ...items,
      { operation: 'split', chunk_index: chunk.chunk_index, split_at: splitAt },
    ])
    setResetPending(false)
  }

  const mergeNext = (index: number) => {
    const chunk = chunks[index]
    const nextChunk = chunks[index + 1]
    if (!nextChunk) return
    const merged = {
      ...chunk,
      id: `${chunk.id}-merged-${nextChunk.id}`,
      text: `${chunk.text}\n${nextChunk.text}`,
      char_end: Math.max(chunk.char_end, nextChunk.char_end),
      metadata: { ...chunk.metadata, split_reason: 'manual_merge' },
    }
    const next = [...chunks.slice(0, index), merged, ...chunks.slice(index + 2)]
    setChunks(next.map((item, chunkIndex) => ({ ...item, chunk_index: chunkIndex })))
    setOperations((items) => [
      ...items,
      {
        operation: 'merge',
        chunk_index: chunk.chunk_index,
        next_chunk_index: nextChunk.chunk_index,
      },
    ])
    setResetPending(false)
  }

  const resetToTemplate = async () => {
    const first = chunks[0]
    const templateId = metadataString(first, 'chunk_template_id') || 'char_window_v1'
    const parameters = (first.metadata.template_parameters as Record<string, unknown>) || {}
    const result = await preview.mutateAsync({
      document_version_id: versionId,
      template_id: templateId,
      parameters,
    })
    setChunks(result.chunks.map((chunk) => ({
      id: `preview-${chunk.chunk_index}`,
      chunk_index: chunk.chunk_index,
      heading: chunk.heading,
      char_start: chunk.char_start,
      char_end: chunk.char_end,
      page_number: null,
      text: chunk.text,
      metadata: chunk.metadata,
    })))
    setOperations([{ operation: 'reset_to_template', template_id: templateId }])
    setResetPending(true)
  }

  const save = async () => {
    if (resetPending) {
      const first = chunks[0]
      await resetOverride.mutateAsync({
        reason,
        template_id: metadataString(first, 'chunk_template_id') || 'char_window_v1',
        template_parameters: (first.metadata.template_parameters as Record<string, unknown>) || {},
      })
    } else {
      const first = chunks[0]
      await saveOverride.mutateAsync({
        reason,
        template_id: metadataString(first, 'chunk_template_id') || 'char_window_v1',
        template_parameters: (first.metadata.template_parameters as Record<string, unknown>) || {},
        chunks: chunks.map((chunk) => ({
          char_start: chunk.char_start,
          char_end: chunk.char_end,
          split_reason: metadataString(chunk, 'split_reason') || 'manual_split',
          heading: chunk.heading,
          source_block_type: metadataString(chunk, 'source_block_type') || 'unknown',
          source_block_id: metadataString(chunk, 'source_block_id') || null,
          section_id: metadataString(chunk, 'section_id') || null,
          table_id: metadataString(chunk, 'table_id') || null,
          parser_page_number: chunk.page_number,
        })),
        operations,
      })
    }
    setOperations([])
    setResetPending(false)
  }

  return (
    <div>
      <div className="px-4 py-2 bg-amber-50 border-b border-amber-100 flex gap-2 items-center flex-wrap">
        <span className="text-[11px] font-medium text-amber-800">
          Index: {review?.index_status.status ?? 'unknown'}
          {review?.index_status.reindex_required ? ' · reindex required' : ''}
        </span>
        {pending && (
          <span className="text-[11px] font-bold text-amber-700">
            {operations.length} pending change(s)
          </span>
        )}
        <input
          aria-label="Chunk override reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="ml-auto border border-amber-200 rounded px-2 py-1 text-xs bg-white"
        />
        <button
          disabled={!review.edit_supported || preview.isPending}
          onClick={resetToTemplate}
          className="px-2 py-1 text-xs border rounded bg-white disabled:opacity-40"
        >
          Reset to template
        </button>
        <button
          disabled={!pending || saveOverride.isPending || resetOverride.isPending}
          onClick={save}
          className="px-2 py-1 text-xs rounded bg-brand text-white disabled:opacity-40"
        >
          Save changes
        </button>
        <button
          disabled={!review.index_status.reindex_required || reindex.isPending}
          onClick={() => reindex.mutate()}
          className="px-2 py-1 text-xs border rounded bg-white disabled:opacity-40"
        >
          Reindex
        </button>
        {!review.edit_supported && (
          <span className="text-[11px] text-red-600">{review.edit_limitation}</span>
        )}
      </div>
      <div className="max-h-[32rem] overflow-y-auto divide-y divide-gray-100">
        {chunks.map((chunk: Chunk, index) => (
          <div key={chunk.id} className="px-4 py-2.5">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[10px] font-bold text-gray-400">#{chunk.chunk_index}</span>
              <span className="text-[10px] font-mono text-indigo-600">
                {metadataString(chunk, 'chunk_template_id')}
              </span>
              <span className="text-[10px] text-amber-700">
                {metadataString(chunk, 'split_reason')}
              </span>
              <span className="text-[10px] text-gray-400">
                {chunk.char_start}:{chunk.char_end}
              </span>
              {chunk.heading && (
                <span className="text-[11px] font-medium text-gray-600 truncate">{chunk.heading}</span>
              )}
              {chunk.page_number != null && (
                <span className="text-[10px] text-gray-400 ml-auto shrink-0">
                  p.{chunk.page_number}
                </span>
              )}
            </div>
            <div className="text-xs text-gray-600 line-clamp-3 whitespace-pre-wrap">{chunk.text}</div>
            <div className="mt-1 flex gap-2 items-center">
              <span className="text-[10px] text-gray-400">
                {metadataString(chunk, 'source_block_type')}{' '}
                {metadataString(chunk, 'source_block_id')}
              </span>
              {metadataString(chunk, 'split_explanation') && (
                <span className="text-[10px] text-gray-400">
                  {metadataString(chunk, 'split_explanation')}
                </span>
              )}
              <button
                disabled={!review.edit_supported}
                onClick={() => splitChunk(index)}
                className="ml-auto text-[10px] text-brand disabled:text-gray-300"
              >
                Split
              </button>
              <button
                disabled={!review.edit_supported || index === chunks.length - 1}
                onClick={() => mergeNext(index)}
                className="text-[10px] text-brand disabled:text-gray-300"
              >
                Merge next
              </button>
            </div>
          </div>
        ))}
      </div>
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
