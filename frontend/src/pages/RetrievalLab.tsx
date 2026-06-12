import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../api/client'
import {
  useKnowledgeBases,
  useRetrieval,
  useRetrievalPreferences,
  useSaveRetrievalPreferences,
} from '../api/hooks'
import type { RerankTrace, RerankTraceRow, RetrievalPreferences, RetrievalReport } from '../api/types'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, MetricCard, Panel, StatusPill } from '../components/console'

type CompareRow = {
  id: string
  mode: string
  result: 'best' | 'stable' | 'review'
  topDocument: string
  evidence: string
}

const MODES = ['hybrid_graph', 'dense', 'hybrid', 'rerank', 'hybrid_rerank', 'graph', 'graph_rerank', 'hybrid_graph_rerank']
const COMPARE_MODES = ['dense', 'graph', 'hybrid_graph']
const RERANKER_OPTIONS = [
  { value: 'reranker.bge', label: 'BGE local', defaultModel: 'BAAI/bge-reranker-v2-m3' },
  { value: 'reranker.jina', label: 'Jina rerank', defaultModel: 'jina-reranker-m0' },
  { value: 'reranker.cohere', label: 'Cohere rerank', defaultModel: 'rerank-v4.0-fast' },
] as const
const DEFAULT_PREFERENCES: RetrievalPreferences = {
  mode: 'hybrid_graph',
  lexical_weight: 0.3,
  vector_weight: 0.7,
  candidate_k: 20,
  reranker_provider: 'reranker.bge',
  reranker_model: 'BAAI/bge-reranker-v2-m3',
  graph_weight: 0.35,
  graph_depth: 1,
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

function stringValue(value: unknown, fallback = '--') {
  if (typeof value === 'string' && value.trim()) return value
  if (typeof value === 'number') return String(value)
  return fallback
}

function clampNumber(raw: string, fallback: number, min: number, max: number) {
  const value = Number(raw)
  if (!Number.isFinite(value)) return fallback
  return Math.min(max, Math.max(min, value))
}

function graphDepth(raw: string, fallback: number) {
  return Math.round(clampNumber(raw, fallback, 0, 2))
}

function candidateK(raw: string, fallback: number) {
  return Math.round(clampNumber(raw, fallback, 1, 200))
}

function topScore(report: RetrievalReport) {
  return report.results[0]?.score ?? 0
}

function graphEvidenceLabel(report: RetrievalReport) {
  const context = report.graph_context ?? {}
  const entities = recordArray(context.matched_entities).length
  const paths = recordArray(context.relation_paths).length
  return `${report.total_results} results, ${entities} entities, ${paths} paths`
}

function modeUsesRerank(activeMode: string) {
  return activeMode.includes('rerank')
}

function defaultRerankerModel(provider: string) {
  return RERANKER_OPTIONS.find((option) => option.value === provider)?.defaultModel ?? ''
}

function formatScore(value: unknown) {
  return typeof value === 'number' ? value.toFixed(4) : '--'
}

function formatLatency(trace: RerankTrace | undefined) {
  return typeof trace?.latency_ms === 'number' ? `${trace.latency_ms.toFixed(1)} ms` : '--'
}

function movementLabel(row: RerankTraceRow) {
  return typeof row.original_rank === 'number' && row.original_rank !== row.rank
    ? `was #${row.original_rank}`
    : 'same rank'
}

function changedLabel(trace: RerankTrace | undefined) {
  const count = trace?.changed_count ?? 0
  return `${count} changed`
}

export default function RetrievalLab() {
  const { data: kbs } = useKnowledgeBases()
  const search = useRetrieval()
  const savePreferences = useSaveRetrievalPreferences()
  const [selectedKbIdOverride, setSelectedKbIdOverride] = useState('')
  const [query, setQuery] = useState('What does the Local Pilot E2E verify about grounded answers and citations?')
  const [topK, setTopK] = useState(8)
  const [modeOverride, setModeOverride] = useState<string | null>(null)
  const [graphWeightOverride, setGraphWeightOverride] = useState<string | null>(null)
  const [graphDepthOverride, setGraphDepthOverride] = useState<string | null>(null)
  const [candidateKOverride, setCandidateKOverride] = useState<string | null>(null)
  const [rerankerProviderOverride, setRerankerProviderOverride] = useState<string | null>(null)
  const [rerankerModelOverride, setRerankerModelOverride] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [compareRows, setCompareRows] = useState<CompareRow[]>([])
  const [comparePending, setComparePending] = useState(false)

  const preferredKb = useMemo(() => {
    const items = kbs ?? []
    return items.find((kb) => kb.name === 'local-pilot-demo-rc') ?? items[0] ?? null
  }, [kbs])
  const selectedKbId = selectedKbIdOverride || preferredKb?.id || ''
  const selectedKb = useMemo(() => {
    return (kbs ?? []).find((kb) => kb.id === selectedKbId) ?? null
  }, [kbs, selectedKbId])
  const preferencesQuery = useRetrievalPreferences(selectedKbId || null)

  const preferences = preferencesQuery.data?.preferences ?? DEFAULT_PREFERENCES
  const mode = modeOverride ?? preferences.mode
  const graphWeight = graphWeightOverride ?? String(preferences.graph_weight)
  const graphDepthValue = graphDepthOverride ?? String(preferences.graph_depth)
  const candidateKValue = candidateKOverride ?? String(preferences.candidate_k)
  const rerankerProvider = rerankerProviderOverride ?? preferences.reranker_provider ?? RERANKER_OPTIONS[0].value
  const rerankerModel = rerankerModelOverride ?? preferences.reranker_model ?? defaultRerankerModel(rerankerProvider)
  const report = search.data
  const results = report?.results ?? []
  const rerankTrace = report?.rerank_trace
  const beforeRows = rerankTrace?.before ?? []
  const afterRows = rerankTrace?.after ?? []
  const graphContext = report?.graph_context ?? {}
  const matchedEntities = recordArray(graphContext.matched_entities)
  const matchedRelationships = recordArray(graphContext.matched_relationships)
  const relationPaths = recordArray(graphContext.relation_paths)
  const rankMovement = recordArray(graphContext.rank_movement)
  const diagnostics = isRecord(graphContext.diagnostics) ? graphContext.diagnostics : {}
  const suppressedRelations = recordArray(diagnostics.suppressed_relations)
  const suppressedCount = Number(diagnostics.suppressed_relation_count ?? suppressedRelations.length) || 0
  const provider = report?.provider ?? 'deterministic-local'
  const model = report?.model || 'default'

  function requestBody(activeMode = mode) {
    const currentDepth = graphDepth(graphDepthValue, preferences.graph_depth)
    const currentWeight = clampNumber(graphWeight, preferences.graph_weight, 0, 1)
    const currentCandidateK = candidateK(candidateKValue, preferences.candidate_k)
    const activeUsesRerank = modeUsesRerank(activeMode)
    return {
      knowledge_base: selectedKb?.name ?? '',
      query: query.trim(),
      top_k: topK,
      provider: 'deterministic-local',
      model: null,
      dimensions: null,
      principal_ids: [],
      enforce_acl: false,
      mode: activeMode,
      lexical_weight: preferences.lexical_weight,
      vector_weight: preferences.vector_weight,
      candidate_k: currentCandidateK,
      reranker_provider: activeUsesRerank ? rerankerProvider : null,
      reranker_model: activeUsesRerank ? rerankerModel || null : null,
      graph_weight: currentWeight,
      graph_depth: currentDepth,
    }
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault()
    if (!selectedKb || !query.trim()) return
    try {
      const result = await search.mutateAsync(requestBody())
      const suffix = result.degraded ? ` Degraded: ${result.degraded_reason ?? 'reranker unavailable'}` : ''
      setMessage(`Search completed in ${mode}: ${result.total_results} results.${suffix}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Search failed.')
    }
  }

  async function handleCompareModes() {
    if (!selectedKb || !query.trim()) return
    setComparePending(true)
    try {
      const reports = await Promise.all(
        COMPARE_MODES.map((candidateMode) =>
          api.post<RetrievalReport>('/retrieval/search', requestBody(candidateMode)),
        ),
      )
      const bestScore = Math.max(...reports.map(topScore), 0)
      const rows = reports.map((candidate, index) => {
        const candidateMode = COMPARE_MODES[index] ?? 'unknown'
        const score = topScore(candidate)
        const result = score > 0 && score === bestScore ? 'best' : candidate.total_results > 0 ? 'stable' : 'review'
        return {
          id: candidateMode,
          mode: candidateMode,
          result,
          topDocument: candidate.results[0]?.document_uri ?? 'No result',
          evidence: graphEvidenceLabel(candidate),
        } satisfies CompareRow
      })
      setCompareRows(rows)
      setMessage(`Compared ${COMPARE_MODES.join(', ')} with live retrieval responses.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Mode comparison failed.')
    } finally {
      setComparePending(false)
    }
  }

  async function handleSaveDefault() {
    if (!selectedKbId || !selectedKb) return
    const payload: RetrievalPreferences = {
      ...preferences,
      mode,
      candidate_k: candidateK(candidateKValue, preferences.candidate_k),
      reranker_provider: rerankerProvider,
      reranker_model: rerankerModel || null,
      graph_weight: clampNumber(graphWeight, preferences.graph_weight, 0, 1),
      graph_depth: graphDepth(graphDepthValue, preferences.graph_depth),
    }
    try {
      await savePreferences.mutateAsync({ kbId: selectedKbId, preferences: payload })
      setModeOverride(payload.mode)
      setGraphWeightOverride(String(payload.graph_weight))
      setGraphDepthOverride(String(payload.graph_depth))
      setCandidateKOverride(String(payload.candidate_k))
      setRerankerProviderOverride(payload.reranker_provider)
      setRerankerModelOverride(payload.reranker_model)
      setMessage(`Saved retrieval defaults for ${selectedKb.name}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Failed to save retrieval defaults.')
    }
  }

  return (
    <ConsolePage
      title="Retrieval Lab"
      description="Graph-aware query lab for comparing dense, graph, hybrid graph, and reranked retrieval paths."
      actions={
        <Button variant="secondary" onClick={handleSaveDefault} disabled={!selectedKbId || savePreferences.isPending}>
          {savePreferences.isPending ? 'Saving...' : 'Save as KB Default'}
        </Button>
      }
    >
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Mode" value={mode} sub="current query strategy" />
        <MetricCard label="Top K" value={topK} sub="candidate window" />
        <MetricCard label="Reranker" value={modeUsesRerank(mode) ? rerankerProvider : 'off'} sub={modeUsesRerank(mode) ? `${candidateKValue} candidates` : 'current mode'} tone={modeUsesRerank(mode) ? 'info' : 'neutral'} />
        <MetricCard label="Rerank latency" value={formatLatency(rerankTrace)} sub={changedLabel(rerankTrace)} tone={report?.degraded ? 'warn' : rerankTrace?.status === 'applied' ? 'ok' : 'neutral'} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel title="Query" description={selectedKb ? selectedKb.name : 'Select a knowledge base.'}>
          <form onSubmit={handleSearch} className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">Knowledge base</span>
                <select
                  id="retrieval-lab-kb-select"
                  value={selectedKbId}
                  onChange={(event) => {
                    setSelectedKbIdOverride(event.target.value)
                    setModeOverride(null)
                    setGraphWeightOverride(null)
                    setGraphDepthOverride(null)
                    setCandidateKOverride(null)
                    setRerankerProviderOverride(null)
                    setRerankerModelOverride(null)
                  }}
                  className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm"
                >
                  <option value="">Select...</option>
                  {(kbs ?? []).map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">Mode</span>
                <select
                  id="retrieval-lab-mode"
                  value={mode}
                  onChange={(event) => setModeOverride(event.target.value)}
                  className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm"
                >
                  {MODES.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              </label>
            </div>
            <label className="space-y-1">
              <span className="text-xs font-medium text-slate-600">Query</span>
              <textarea
                id="retrieval-lab-query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="min-h-28 w-full resize-y rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand/30"
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">Top K</span>
                <input
                  id="retrieval-lab-top-k"
                  type="number"
                  min={1}
                  max={50}
                  value={topK}
                  onChange={(event) => setTopK(Number(event.target.value))}
                  className="w-full rounded-lg border border-line px-3 py-2 text-sm"
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">Graph depth</span>
                <input
                  id="retrieval-lab-graph-depth"
                  type="number"
                  min={0}
                  max={2}
                  value={graphDepthValue}
                  onChange={(event) => setGraphDepthOverride(event.target.value)}
                  className="w-full rounded-lg border border-line px-3 py-2 text-sm"
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">Graph weight</span>
                <input
                  id="retrieval-lab-graph-weight"
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={graphWeight}
                  onChange={(event) => setGraphWeightOverride(event.target.value)}
                  className="w-full rounded-lg border border-line px-3 py-2 text-sm"
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">Candidate K</span>
                <input
                  id="retrieval-lab-candidate-k"
                  type="number"
                  min={1}
                  max={200}
                  value={candidateKValue}
                  onChange={(event) => setCandidateKOverride(event.target.value)}
                  className="w-full rounded-lg border border-line px-3 py-2 text-sm"
                />
              </label>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">Reranker provider</span>
                <select
                  id="retrieval-lab-reranker-provider"
                  value={rerankerProvider}
                  onChange={(event) => {
                    const nextProvider = event.target.value
                    setRerankerProviderOverride(nextProvider)
                    setRerankerModelOverride(defaultRerankerModel(nextProvider))
                  }}
                  className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm"
                >
                  {RERANKER_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">Reranker model</span>
                <input
                  id="retrieval-lab-reranker-model"
                  value={rerankerModel}
                  onChange={(event) => setRerankerModelOverride(event.target.value)}
                  className="w-full rounded-lg border border-line px-3 py-2 text-sm"
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={search.isPending || !selectedKb || !query.trim()}>
                {search.isPending ? 'Searching...' : 'Search'}
              </Button>
              <Button variant="secondary" onClick={handleCompareModes} disabled={comparePending || !selectedKb || !query.trim()}>
                {comparePending ? 'Comparing...' : 'Compare Modes'}
              </Button>
            </div>
          </form>
        </Panel>

        <Panel title="Rerank Trace" description={rerankTrace ? `${rerankTrace.provider ?? 'reranker'} / ${rerankTrace.model || 'default'}` : 'Run a reranked search to inspect ordering changes.'}>
          {report?.degraded && (
            <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {report.degraded_reason ?? rerankTrace?.degraded_reason ?? 'Reranker unavailable.'}
            </div>
          )}
          {rerankTrace ? (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-3">
                <MetricCard label="Provider" value={rerankTrace.provider ?? '--'} sub={rerankTrace.model || 'default model'} tone={report?.degraded ? 'warn' : 'info'} />
                <MetricCard label="Latency" value={formatLatency(rerankTrace)} sub={`${rerankTrace.candidate_count ?? 0} candidates`} tone={report?.degraded ? 'warn' : 'ok'} />
                <MetricCard label="Movement" value={changedLabel(rerankTrace)} sub={rerankTrace.status ?? 'not run'} tone={(rerankTrace.changed_count ?? 0) > 0 ? 'ok' : 'neutral'} />
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                <section role="region" aria-label="Before rerank" className="rounded-lg border border-line bg-white p-3">
                  <div className="text-xs font-semibold uppercase tracking-wider text-muted">Before rerank</div>
                  <div className="mt-3 space-y-2">
                    {beforeRows.length ? beforeRows.slice(0, 6).map((row) => (
                      <div key={`before-${row.chunk_id ?? row.document_uri}-${row.rank}`} className="grid grid-cols-[44px_1fr_auto] items-center gap-2 text-sm">
                        <span className="font-mono text-xs text-muted">#{row.rank}</span>
                        <span className="truncate font-mono text-xs text-slate-700">{row.document_uri}</span>
                        <span className="font-mono text-xs text-slate-500">{formatScore(row.score)}</span>
                      </div>
                    )) : <div className="text-sm text-muted">No before-rerank rows.</div>}
                  </div>
                </section>
                <section role="region" aria-label="After rerank" className="rounded-lg border border-line bg-white p-3">
                  <div className="text-xs font-semibold uppercase tracking-wider text-muted">After rerank</div>
                  <div className="mt-3 space-y-2">
                    {afterRows.length ? afterRows.slice(0, 6).map((row) => (
                      <div key={`after-${row.chunk_id ?? row.document_uri}-${row.rank}`} className="grid grid-cols-[44px_1fr_auto_auto] items-center gap-2 text-sm">
                        <span className="font-mono text-xs text-brand">#{row.rank}</span>
                        <span className="truncate font-mono text-xs text-slate-700">{row.document_uri}</span>
                        <span className="font-mono text-xs text-slate-500">{formatScore(row.rerank_score ?? row.score)}</span>
                        <span className="rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-xs text-slate-600">{movementLabel(row)}</span>
                      </div>
                    )) : <div className="text-sm text-muted">No after-rerank rows.</div>}
                  </div>
                </section>
              </div>
            </div>
          ) : (
            <div className="text-sm text-muted">No rerank trace yet.</div>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <Panel title="Mode Comparison" description={compareRows.length ? 'Live comparison results.' : 'Run a comparison to populate this board.'}>
          {compareRows.length ? (
            <DataTable
              rows={compareRows}
              getKey={(row) => row.id}
              columns={[
                { key: 'mode', label: 'Mode', render: (row) => <span className="font-mono text-xs">{row.mode}</span> },
                { key: 'result', label: 'Result', render: (row) => <StatusPill tone={row.result === 'best' ? 'ok' : row.result === 'review' ? 'warn' : 'info'}>{row.result}</StatusPill> },
                { key: 'topDocument', label: 'Top result', render: (row) => <span className="font-mono text-xs text-slate-600">{row.topDocument}</span> },
                { key: 'evidence', label: 'Evidence', render: (row) => row.evidence },
              ]}
            />
          ) : (
            <div className="text-sm text-muted">No comparison run yet.</div>
          )}
        </Panel>
        <Panel title="Results" description={report ? `${results.length} results - ${provider} / ${model}` : 'No search run yet.'}>
          {results.length ? (
            <div className="space-y-3" id="retrieval-lab-results">
              {results.map((result, index) => (
                <div key={result.chunk_id} className="rounded-xl border border-blue-100 bg-blue-50/35 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="font-medium text-ink">#{index + 1} {result.document_uri}</div>
                    <span className="rounded-full border border-blue-200 bg-white px-2 py-0.5 font-mono text-xs text-brand">
                      score {typeof result.score === 'number' ? result.score.toFixed(4) : '--'}
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-slate-700">{result.text_preview}</p>
                  <pre className="mt-3 overflow-x-auto rounded-lg border border-line bg-white p-3 text-xs text-slate-600">
                    {JSON.stringify(result.rank_stage_trace ?? { trace: 'not available' }, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted" id="retrieval-lab-results">Run a search to load retrieval results.</div>
          )}
        </Panel>

        <Panel title="Graph Context" description={report ? `${matchedEntities.length} entities, ${matchedRelationships.length} relationships.` : 'No graph context loaded.'}>
          <div className="space-y-3" id="retrieval-lab-graph-context">
            <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-semibold uppercase tracking-wider text-muted">Matched entities</div>
                <StatusPill tone={matchedEntities.length ? 'ok' : 'neutral'}>{matchedEntities.length}</StatusPill>
              </div>
              <div className="mt-2 text-sm text-slate-700">
                {matchedEntities.length
                  ? matchedEntities.map((entity) => stringValue(entity.display_name ?? entity.name ?? entity.entity)).join(', ')
                  : 'None'}
              </div>
            </div>
            <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-semibold uppercase tracking-wider text-muted">Matched relationships</div>
                <StatusPill tone={matchedRelationships.length ? 'ok' : 'neutral'}>{matchedRelationships.length}</StatusPill>
              </div>
              <div className="mt-2 space-y-2 text-sm text-slate-700">
                {matchedRelationships.length ? matchedRelationships.slice(0, 4).map((relation, index) => (
                  <div key={`${stringValue(relation.relation_id, String(index))}-${index}`}>
                    {stringValue(relation.subject)} - {stringValue(relation.predicate)} - {stringValue(relation.object)}
                  </div>
                )) : <div>None</div>}
              </div>
            </div>
            <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-semibold uppercase tracking-wider text-muted">Relation paths</div>
                <StatusPill tone={relationPaths.length ? 'ok' : 'neutral'}>{relationPaths.length}</StatusPill>
              </div>
              <div className="mt-2 space-y-2 text-sm text-slate-700">
                {relationPaths.length ? (
                  relationPaths.slice(0, 4).map((path, index) => (
                    <div key={`${stringValue(path.relation_id, String(index))}-${index}`}>
                      {stringValue(path.subject)} - {stringValue(path.predicate)} - {stringValue(path.object)}
                    </div>
                  ))
                ) : (
                  <div>None</div>
                )}
              </div>
            </div>
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-amber-700">Suppressed relations</div>
              <div className="mt-2 text-sm text-amber-800">{suppressedCount}</div>
              {suppressedRelations.slice(0, 3).map((relation, index) => (
                <div key={`${stringValue(relation.relation_id, String(index))}-suppressed`} className="mt-1 text-xs text-amber-800">
                  {stringValue(relation.subject)} - {stringValue(relation.predicate)} - {stringValue(relation.object)}: {stringValue(relation.reason)}
                </div>
              ))}
            </div>
            <div className="rounded-lg border border-line bg-white p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted">Graph rank movement</div>
              <div className="mt-2 space-y-1 text-xs text-slate-700">
                {rankMovement.length ? rankMovement.slice(0, 4).map((movement, index) => (
                  <div key={`${stringValue(movement.chunk_id, String(index))}-movement`}>
                    {stringValue(movement.chunk_id)}: #{stringValue(movement.rank_before, 'new')} to #{stringValue(movement.rank_after)}
                  </div>
                )) : <div>None</div>}
              </div>
            </div>
          </div>
        </Panel>
      </div>
    </ConsolePage>
  )
}
