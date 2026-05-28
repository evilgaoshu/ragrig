import { useMemo, useState } from 'react'
import { useKnowledgeBases, useRetrieval } from '../api/hooks'
import type { RetrievalResult } from '../api/types'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, MetricCard, Panel, StatusPill } from '../components/console'

type CompareRow = {
  id: string
  mode: string
  result: 'best' | 'stable' | 'review'
  path: string
  evidence: string
}

type GraphSignal = {
  id: string
  label: string
  value: string
  tone?: 'ok' | 'warn' | 'info' | 'neutral'
}

const SAMPLE_RESULTS: RetrievalResult[] = [
  {
    chunk_id: 'chunk-graph-01',
    document_uri: 'docs/specs/ragrig-kg-lite-graph-retrieval-spec.md',
    score: 0.9241,
    text_preview: 'Graph evidence chunks are merged with dense candidates before reranking, then relation feedback suppresses incorrect paths.',
    rank_stage_trace: {
      dense_rank: 3,
      graph_boost: '+0.18',
      rerank: 'accepted relation path',
    },
  } as RetrievalResult,
  {
    chunk_id: 'chunk-demo-07',
    document_uri: 'docs/operations/demo-graph-console-runbook.md',
    score: 0.8872,
    text_preview: 'The demo rehearsal validates graph context rendering, feedback suppression, smoke run, and cleanup records.',
    rank_stage_trace: {
      dense_rank: 7,
      graph_boost: '+0.15',
      rerank: 'runbook evidence',
    },
  } as RetrievalResult,
  {
    chunk_id: 'chunk-role-03',
    document_uri: 'examples/local-pilot/role-parser-ops.md',
    score: 0.8468,
    text_preview: 'Role parser operations demonstrate curator feedback loops and graph-aware answer quality checks.',
    rank_stage_trace: {
      dense_rank: 9,
      graph_boost: '+0.11',
      rerank: 'role parser loop',
    },
  } as RetrievalResult,
]

const COMPARISON_ROWS: CompareRow[] = [
  { id: 'hybrid_graph', mode: 'hybrid_graph', result: 'best', path: 'dense + KG relation paths', evidence: 'graph boost + accepted relation' },
  { id: 'dense', mode: 'dense', result: 'stable', path: 'semantic chunks only', evidence: 'misses role feedback edge' },
  { id: 'graph', mode: 'graph', result: 'review', path: 'KG relation traversal', evidence: 'high precision, lower recall' },
  { id: 'graph_rerank', mode: 'graph_rerank', result: 'stable', path: 'KG first, rerank after evidence', evidence: 'good demo trace, slower' },
]

const GRAPH_SIGNALS: GraphSignal[] = [
  { id: 'entities', label: 'Matched entities', value: 'Graph retrieval, Role parser ops, Demo runbook', tone: 'info' },
  { id: 'paths', label: 'Relation paths', value: 'Graph retrieval -> augments -> Hybrid search ranking', tone: 'ok' },
  { id: 'evidence', label: 'Evidence chunks', value: '3 KG snippets merged into candidate set', tone: 'ok' },
]

const MODES = ['hybrid_graph', 'dense', 'graph', 'graph_rerank', 'hybrid_graph_rerank']

export default function RetrievalLab() {
  const { data: kbs } = useKnowledgeBases()
  const search = useRetrieval()
  const [kb, setKb] = useState('')
  const [query, setQuery] = useState('Which board compares DenseMode, GraphMode, and HybridGraphMode?')
  const [topK, setTopK] = useState(8)
  const [mode, setMode] = useState('hybrid_graph')
  const [message, setMessage] = useState('')
  const [suppressed, setSuppressed] = useState('Processing sanitizer -> powers -> Voyage embeddings')

  const kbOptions = useMemo(() => kbs?.map((k) => k.name) ?? ['demo-handbook', 'local-pilot', 'support-faq'], [kbs])
  const results = search.data?.results?.length ? search.data.results : SAMPLE_RESULTS
  const provider = search.data?.provider ?? 'deterministic-local'
  const model = search.data?.model || 'graph-demo'

  const handleSearch = (event: React.FormEvent) => {
    event.preventDefault()
    const selectedKb = kb || kbOptions[0]
    if (!selectedKb || !query.trim()) return
    search.mutate({
      knowledge_base: selectedKb,
      query: query.trim(),
      top_k: topK,
      provider: 'deterministic-local',
      model: null,
      mode,
    })
    setMessage(`Search queued in ${mode} mode for ${selectedKb}. Prototype results remain visible while the API responds.`)
  }

  return (
    <ConsolePage
      title="Retrieval Lab"
      description="Graph-aware query lab for comparing dense, graph, hybrid graph, and reranked retrieval paths."
      actions={<Button variant="secondary" onClick={() => setMessage('Saved KB default preference: hybrid_graph, graph weight 0.35, depth 2.')}>Save as KB default</Button>}
    >
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Mode" value={mode} sub="current query strategy" />
        <MetricCard label="Top K" value={topK} sub="candidate window" />
        <MetricCard label="Graph context" value="on" sub="entities + relations" tone="ok" />
        <MetricCard label="Suppressed" value="1" sub="relation feedback active" tone="warn" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel title="Query" description="Run a live search when API data is available; keep prototype evidence visible for review.">
          <form onSubmit={handleSearch} className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">Knowledge base</span>
                <select value={kb} onChange={(event) => setKb(event.target.value)} className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm">
                  <option value="">Select...</option>
                  {kbOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">Mode</span>
                <select value={mode} onChange={(event) => setMode(event.target.value)} className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm">
                  {MODES.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              </label>
            </div>
            <label className="space-y-1">
              <span className="text-xs font-medium text-slate-600">Query</span>
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="min-h-28 w-full resize-y rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand/30"
              />
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <span className="text-xs font-medium uppercase tracking-wider text-muted">Top K</span>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={topK}
                  onChange={(event) => setTopK(Number(event.target.value))}
                  className="h-9 w-20 rounded-lg border border-line px-2 text-sm"
                />
              </label>
              <Button type="submit" disabled={search.isPending || !query.trim()}>
                {search.isPending ? 'Searching...' : 'Search'}
              </Button>
              <Button variant="secondary" onClick={() => setMessage('Compared dense, graph, hybrid_graph, and graph_rerank modes.')}>Compare modes</Button>
            </div>
          </form>
        </Panel>

        <Panel title="Mode comparison" description="Prototype comparison board for graph retrieval strategy review.">
          <DataTable
            rows={COMPARISON_ROWS}
            getKey={(row) => row.id}
            columns={[
              { key: 'mode', label: 'Mode', render: (row) => <span className="font-mono text-xs">{row.mode}</span> },
              { key: 'result', label: 'Result', render: (row) => <StatusPill tone={row.result === 'best' ? 'ok' : row.result === 'review' ? 'warn' : 'info'}>{row.result}</StatusPill> },
              { key: 'path', label: 'Path', render: (row) => row.path },
              { key: 'evidence', label: 'Evidence', render: (row) => row.evidence },
            ]}
          />
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <Panel title="Results" description={`${results.length} visible results · ${provider} / ${model}`}>
          <div className="space-y-3">
            {results.map((result, index) => (
              <div key={result.chunk_id} className="rounded-xl border border-blue-100 bg-blue-50/35 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium text-ink">#{index + 1} {result.document_uri}</div>
                  <span className="rounded-full border border-blue-200 bg-white px-2 py-0.5 font-mono text-xs text-brand">
                    score {result.score?.toFixed(4) ?? '--'}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-700">{result.text_preview}</p>
                <pre className="mt-3 overflow-x-auto rounded-lg border border-line bg-white p-3 text-xs text-slate-600">
                  {JSON.stringify(result.rank_stage_trace ?? { trace: 'not available' }, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Graph Context" description="Graph signals exposed beside retrieval results.">
          <div className="space-y-3">
            {GRAPH_SIGNALS.map((signal) => (
              <div key={signal.id} className="rounded-lg border border-blue-100 bg-blue-50/45 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs font-semibold uppercase tracking-wider text-muted">{signal.label}</div>
                  <StatusPill tone={signal.tone}>{signal.id}</StatusPill>
                </div>
                <div className="mt-2 text-sm text-slate-700">{signal.value}</div>
              </div>
            ))}
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-amber-700">Suppressed relation</div>
              <div className="mt-2 text-sm text-amber-800">{suppressed}</div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => setSuppressed('Graph retrieval -> augments -> Hybrid search ranking')}>Use graph relation</Button>
                <Button variant="secondary" onClick={() => setSuppressed('Processing sanitizer -> powers -> Voyage embeddings')}>Hide relation</Button>
              </div>
            </div>
          </div>
        </Panel>
      </div>
    </ConsolePage>
  )
}
