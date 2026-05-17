import { useEffect, useMemo, useState } from 'react'
import {
  useConversations,
  useConversation,
  useCreateConversation,
  useConversationAnswer,
  useDeleteConversation,
  useSubmitFeedback,
  useKnowledgeBases,
  type ConversationTurn,
} from '../api/hooks'

function CitationChips({ citations }: { citations: ConversationTurn['citations'] }) {
  if (!citations || citations.length === 0) {
    return <div className="text-[11px] text-gray-400">No citations.</div>
  }
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {citations.map((c, i) => {
        const hasSpan = c.char_start != null && c.char_end != null
        const page = c.page_number != null ? `p${c.page_number}` : null
        const span = hasSpan ? `[${c.char_start}-${c.char_end}]` : null
        return (
          <span
            key={c.citation_id ?? `${i}`}
            title={c.text_preview ?? ''}
            className="inline-flex items-center gap-1 rounded border border-brand/30 bg-brand/5 px-1.5 py-0.5 text-[11px] text-brand font-medium"
          >
            <span>#{i + 1}</span>
            <span className="truncate max-w-[160px]">{c.document_uri ?? c.chunk_id ?? '?'}</span>
            {page && <span className="text-gray-500">{page}</span>}
            {span && <span className="text-gray-400 font-mono">{span}</span>}
          </span>
        )
      })}
    </div>
  )
}

function highlightAnswer(answer: string, citations: ConversationTurn['citations']) {
  // Inline-highlight any citation char-spans that fall inside the answer text.
  // Char offsets are over the source chunk text, NOT the answer; we approximate
  // by also rendering the text_preview as a quoted block under the answer.
  // Visible UI value: the reader sees both the synthesized answer and the
  // exact source spans the model leaned on.
  const previews = citations
    .filter((c) => c.text_preview)
    .map((c, i) => ({
      id: c.citation_id ?? String(i),
      idx: i + 1,
      preview: c.text_preview ?? '',
      span: c.char_start != null && c.char_end != null ? `[${c.char_start}-${c.char_end}]` : '',
      page: c.page_number != null ? `p${c.page_number}` : '',
      uri: c.document_uri ?? c.chunk_id ?? '?',
    }))
  return (
    <div className="space-y-3">
      <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-gray-900">
        {answer}
      </div>
      {previews.length > 0 && (
        <details className="rounded border border-gray-200 bg-gray-50">
          <summary className="cursor-pointer px-3 py-1.5 text-[11px] font-semibold text-gray-600 select-none">
            Source spans ({previews.length})
          </summary>
          <div className="p-3 space-y-2">
            {previews.map((p) => (
              <div
                key={p.id}
                className="rounded border-l-2 border-brand/40 bg-white px-3 py-2"
              >
                <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-gray-500 mb-1">
                  <span className="font-bold text-brand">#{p.idx}</span>
                  <span className="truncate">{p.uri}</span>
                  {p.page && <span>{p.page}</span>}
                  {p.span && <span className="font-mono">{p.span}</span>}
                </div>
                <div className="text-[12px] text-gray-700 italic">
                  <span className="bg-yellow-100 px-1 rounded">{p.preview}</span>
                </div>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

function FeedbackButtons({
  turnId,
  query,
  answerExcerpt,
}: {
  turnId: string
  query: string
  answerExcerpt: string
}) {
  const submit = useSubmitFeedback()
  const [submitted, setSubmitted] = useState<-1 | 0 | 1 | null>(null)
  const [showReason, setShowReason] = useState(false)
  const [reason, setReason] = useState('')

  const rate = (rating: -1 | 1) => {
    submit.mutate(
      { turn_id: turnId, rating, query, answer_excerpt: answerExcerpt.slice(0, 1900) },
      { onSuccess: () => setSubmitted(rating) },
    )
    if (rating === -1) setShowReason(true)
  }

  const submitReason = () => {
    if (!reason.trim()) return
    submit.mutate(
      {
        turn_id: turnId,
        rating: -1,
        reason: reason.trim(),
        query,
        answer_excerpt: answerExcerpt.slice(0, 1900),
      },
      {
        onSuccess: () => {
          setShowReason(false)
          setReason('')
        },
      },
    )
  }

  return (
    <div className="mt-2 flex items-center gap-2 text-[11px]">
      <button
        type="button"
        onClick={() => rate(1)}
        disabled={submit.isPending}
        className={`px-1.5 py-0.5 rounded border ${
          submitted === 1
            ? 'bg-green-100 border-green-300 text-green-700'
            : 'border-gray-300 text-gray-600 hover:bg-gray-50'
        }`}
      >
        👍 helpful
      </button>
      <button
        type="button"
        onClick={() => rate(-1)}
        disabled={submit.isPending}
        className={`px-1.5 py-0.5 rounded border ${
          submitted === -1
            ? 'bg-red-100 border-red-300 text-red-700'
            : 'border-gray-300 text-gray-600 hover:bg-gray-50'
        }`}
      >
        👎 not helpful
      </button>
      {submitted != null && !showReason && (
        <span className="text-gray-400">thanks for the feedback</span>
      )}
      {showReason && (
        <div className="flex items-center gap-1.5 flex-1">
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="what was wrong?"
            className="flex-1 max-w-md border border-gray-300 rounded px-2 py-0.5 text-[11px]"
          />
          <button
            type="button"
            onClick={submitReason}
            disabled={!reason.trim() || submit.isPending}
            className="px-2 py-0.5 rounded bg-brand text-white disabled:opacity-50"
          >
            send
          </button>
        </div>
      )}
    </div>
  )
}

export default function Conversations() {
  const { data: kbs } = useKnowledgeBases()
  const { data: conversations, isLoading } = useConversations()
  const create = useCreateConversation()
  const del = useDeleteConversation()
  const ask = useConversationAnswer()

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [kbName, setKbName] = useState<string>('')
  const [newTitle, setNewTitle] = useState<string>('')
  const [query, setQuery] = useState<string>('')

  useEffect(() => {
    if (!selectedId && conversations && conversations.length > 0) {
      setSelectedId(conversations[0].id)
    }
  }, [conversations, selectedId])

  useEffect(() => {
    if (!kbName && kbs && kbs.length > 0) {
      setKbName(kbs[0].name)
    }
  }, [kbs, kbName])

  const { data: detail } = useConversation(selectedId)
  const currentKb = detail?.knowledge_base ?? kbName

  const sortedTurns = useMemo(
    () => (detail?.turns ?? []).slice().sort((a, b) => a.turn_index - b.turn_index),
    [detail],
  )

  const handleCreate = () => {
    if (!kbName) return
    create.mutate(
      { knowledge_base: kbName, title: newTitle.trim() || null },
      {
        onSuccess: (data) => {
          setSelectedId(data.id)
          setNewTitle('')
        },
      },
    )
  }

  const handleAsk = (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedId || !query.trim()) return
    const q = query.trim()
    setQuery('')
    ask.mutate({
      id: selectedId,
      body: { query: q, knowledge_base: currentKb || undefined, history_window: 3 },
    })
  }

  return (
    <div className="flex h-full">
      {/* Conversation list */}
      <aside className="w-64 shrink-0 border-r border-gray-200 bg-white p-3 overflow-y-auto">
        <div className="mb-3">
          <label className="block text-[10px] uppercase tracking-wider text-gray-500 mb-1">
            Knowledge base
          </label>
          <select
            value={kbName}
            onChange={(e) => setKbName(e.target.value)}
            className="w-full text-[12px] border border-gray-300 rounded px-2 py-1"
          >
            {!kbs?.length && <option value="">no KBs available</option>}
            {kbs?.map((kb) => (
              <option key={kb.id} value={kb.name}>
                {kb.name}
              </option>
            ))}
          </select>
        </div>
        <div className="mb-3 flex gap-1">
          <input
            type="text"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="new conversation title (optional)"
            className="flex-1 min-w-0 text-[12px] border border-gray-300 rounded px-2 py-1"
          />
          <button
            type="button"
            onClick={handleCreate}
            disabled={create.isPending || !kbName}
            className="px-2 py-1 rounded bg-brand text-white text-[12px] disabled:opacity-50"
          >
            +
          </button>
        </div>
        <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Recent</div>
        {isLoading && <div className="text-[11px] text-gray-400">Loading…</div>}
        {conversations?.length === 0 && (
          <div className="text-[11px] text-gray-400">No conversations yet.</div>
        )}
        <ul className="space-y-1">
          {conversations?.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => setSelectedId(c.id)}
                className={`w-full text-left px-2 py-1.5 rounded text-[12px] transition-colors ${
                  selectedId === c.id
                    ? 'bg-brand/10 text-brand font-semibold'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
              >
                <div className="truncate">{c.title || '(untitled)'}</div>
                <div className="text-[10px] text-gray-400 flex justify-between">
                  <span className="truncate">{c.knowledge_base ?? '—'}</span>
                  <span>{c.turn_count} turns</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* Chat panel */}
      <section className="flex-1 flex flex-col overflow-hidden">
        {!selectedId ? (
          <div className="m-auto text-gray-400 text-sm">
            Select or create a conversation to begin.
          </div>
        ) : (
          <>
            <header className="border-b border-gray-200 px-6 py-3 flex items-center justify-between bg-white">
              <div>
                <h1 className="text-base font-bold text-gray-900">
                  {detail?.title || '(untitled conversation)'}
                </h1>
                <p className="text-[11px] text-gray-500 mt-0.5">
                  KB: <span className="font-medium">{currentKb || '—'}</span>
                  {' · '}
                  {sortedTurns.length} turn{sortedTurns.length === 1 ? '' : 's'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  if (!confirm('Delete this conversation?')) return
                  del.mutate(selectedId, { onSuccess: () => setSelectedId(null) })
                }}
                className="text-[11px] text-gray-500 hover:text-red-500"
              >
                delete
              </button>
            </header>

            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
              {sortedTurns.length === 0 && (
                <div className="text-[12px] text-gray-400 italic">
                  Ask a question to start the conversation.
                </div>
              )}
              {sortedTurns.map((turn) => (
                <div key={turn.id} className="space-y-2">
                  <div className="text-[12px] font-semibold text-gray-700">You asked:</div>
                  <div className="rounded bg-gray-100 px-3 py-2 text-[13px] text-gray-900">
                    {turn.query}
                  </div>
                  <div className="text-[12px] font-semibold text-gray-700 flex items-center gap-2">
                    <span>Assistant:</span>
                    {turn.grounding_status && (
                      <span
                        className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded ${
                          turn.grounding_status === 'grounded'
                            ? 'bg-green-100 text-green-700'
                            : turn.grounding_status === 'refused'
                              ? 'bg-yellow-100 text-yellow-800'
                              : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {turn.grounding_status}
                      </span>
                    )}
                  </div>
                  <div className="rounded border border-gray-200 bg-white px-3 py-2">
                    {highlightAnswer(turn.answer, turn.citations)}
                    <CitationChips citations={turn.citations} />
                    <FeedbackButtons
                      turnId={turn.id}
                      query={turn.query}
                      answerExcerpt={turn.answer}
                    />
                  </div>
                </div>
              ))}
              {ask.isPending && (
                <div className="text-[12px] text-gray-500 italic animate-pulse">
                  Thinking…
                </div>
              )}
              {ask.isError && (
                <div className="text-[12px] text-red-600">
                  {(ask.error as Error).message}
                </div>
              )}
            </div>

            <form
              onSubmit={handleAsk}
              className="border-t border-gray-200 px-6 py-3 bg-white flex gap-2"
            >
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask a follow-up…"
                className="flex-1 border border-gray-300 rounded px-3 py-1.5 text-[13px]"
                disabled={ask.isPending}
              />
              <button
                type="submit"
                disabled={ask.isPending || !query.trim()}
                className="px-4 py-1.5 rounded bg-brand text-white text-[13px] disabled:opacity-50"
              >
                Send
              </button>
            </form>
          </>
        )}
      </section>
    </div>
  )
}
