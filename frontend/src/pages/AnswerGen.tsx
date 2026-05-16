import { useState } from 'react'
import { useKnowledgeBases, useAnswerGen } from '../api/hooks'

type Citation = {
  citation_id: string
  document_uri: string
  chunk_id: string
  chunk_index: number
  text_preview: string
  score: number
}

type AnswerResult = {
  answer: string
  citations: Citation[]
  model: string
  provider: string
  grounding_status: string
  refusal_reason?: string
}

const PROVIDERS = ['deterministic-local', 'openai', 'anthropic', 'ollama', 'cohere']

export default function AnswerGen() {
  const { data: kbs } = useKnowledgeBases()
  const answerGen = useAnswerGen()

  const [kbName, setKbName] = useState('')
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [provider, setProvider] = useState('deterministic-local')
  const [model, setModel] = useState('')
  const [answerProvider, setAnswerProvider] = useState('openai')
  const [answerModel, setAnswerModel] = useState('gpt-4o-mini')
  const [result, setResult] = useState<AnswerResult | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!kbName || !query) return
    try {
      const res = await answerGen.mutateAsync({
        knowledge_base: kbName,
        query,
        top_k: topK,
        provider,
        model: model || null,
        answer_provider: answerProvider,
        answer_model: answerModel || null,
        dimensions: null,
        principal_ids: [],
        enforce_acl: false,
      })
      setResult(res as AnswerResult)
    } catch {
      // error shown via answerGen.error
    }
  }

  const groundingColor =
    result?.grounding_status === 'grounded'
      ? 'text-emerald-600 bg-emerald-50 border-emerald-200'
      : result?.grounding_status === 'refused'
        ? 'text-amber-600 bg-amber-50 border-amber-200'
        : 'text-gray-500 bg-gray-100 border-gray-200'

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Answer Gen</h1>
        <p className="text-gray-500 text-sm mt-0.5">Grounded answer generation playground</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          {/* KB */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-600">Knowledge base</label>
            <select
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
              value={kbName}
              onChange={(e) => setKbName(e.target.value)}
              required
            >
              <option value="">— select —</option>
              {(kbs ?? []).map((kb) => (
                <option key={kb.id} value={kb.name}>{kb.name}</option>
              ))}
            </select>
          </div>

          {/* Top K */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-600">Top K</label>
            <input
              type="number" min={1} max={50}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            />
          </div>
        </div>

        {/* Retrieval provider */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-600">Retrieval provider</label>
            <select
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-600">Retrieval model <span className="text-gray-400">(optional)</span></label>
            <input
              type="text" placeholder="default"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
          </div>
        </div>

        {/* Answer provider */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-600">Answer provider</label>
            <select
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
              value={answerProvider}
              onChange={(e) => setAnswerProvider(e.target.value)}
            >
              {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-600">Answer model</label>
            <input
              type="text" placeholder="gpt-4o-mini"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
              value={answerModel}
              onChange={(e) => setAnswerModel(e.target.value)}
            />
          </div>
        </div>

        {/* Query */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-gray-600">Query</label>
          <textarea
            rows={3}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 resize-none"
            placeholder="Ask a question…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            required
          />
        </div>

        {answerGen.isError && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            {answerGen.error instanceof Error ? answerGen.error.message : 'Request failed'}
          </div>
        )}

        <button
          type="submit"
          disabled={!kbName || !query || answerGen.isPending}
          className="px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {answerGen.isPending ? 'Generating…' : 'Generate answer'}
        </button>
      </form>

      {result && (
        <div className="space-y-4 border-t border-gray-200 pt-6">
          {/* Answer */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold text-gray-600">Answer</span>
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${groundingColor}`}>
                {result.grounding_status}
              </span>
              <span className="text-xs text-gray-400">{result.provider} · {result.model}</span>
            </div>
            {result.refusal_reason ? (
              <div className="text-sm text-amber-600 italic">{result.refusal_reason}</div>
            ) : result.answer ? (
              <div className="text-sm text-gray-800 whitespace-pre-wrap bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 leading-relaxed">
                {result.answer}
              </div>
            ) : (
              <div className="text-sm text-gray-400 italic">No answer generated.</div>
            )}
          </div>

          {/* Citations */}
          {result.citations.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-gray-600 mb-2">
                Citations ({result.citations.length})
              </div>
              <div className="space-y-2">
                {result.citations.map((c) => (
                  <div key={c.citation_id} className="bg-white border border-gray-200 rounded-lg px-3 py-2.5">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[10px] font-bold text-gray-400">#{c.citation_id}</span>
                      <span className="text-xs font-mono text-gray-600 truncate">{c.document_uri}</span>
                      <span className="ml-auto text-[10px] text-gray-400 shrink-0">
                        score {c.score.toFixed(3)}
                      </span>
                    </div>
                    <div className="text-xs text-gray-600 line-clamp-3">{c.text_preview}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
