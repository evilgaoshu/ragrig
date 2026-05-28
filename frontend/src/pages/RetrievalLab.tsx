import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../api/client'
import {
  useKnowledgeBases,
  useRetrieval,
  useRetrievalPreferences,
  useSaveRetrievalPreferences,
} from '../api/hooks'
import type { RetrievalPreferences, RetrievalReport } from '../api/types'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, MetricCard, Panel, StatusPill } from '../components/console'

type CompareRow = {
  id: string
  mode: string
  result: 'best' | 'stable' | 'review'
  topDocument: string
  evidence: string
}

const MODES = ['hybrid_graph', 'dense', 'hybrid', 'graph', 'graph_rerank', 'hybrid_graph_rerank']
const COMPARE_MODES = ['dense', 'graph', 'hybrid_graph']
const DEFAULT_PREFERENCES: RetrievalPreferences = {
  mode: 'hybrid_graph',
  lexical_weight: 0.3,
  vector_weight: 0.7,
  candidate_k: 20,
  reranker_provider: null,
  reranker_model: null,
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

function topScore(report: RetrievalReport) {
  return report.results[0]?.score ?? 0
}

function graphEvidenceLabel(report: RetrievalReport) {
  const context = report.graph_context ?? {}
  const entities = recordArray(context.matched_entities).length
  const paths = recordArray(context.relation_paths).length
  return `${report.total_results} results, ${entities} entities, ${paths} paths`
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
  const report = search.data
  const results = report?.results ?? []
  const graphContext = report?.graph_context ?? {}
  const matchedEntities = recordArray(graphContext.matched_entities)
  const relationPaths = recordArray(graphContext.relation_paths)
  const diagnostics = isRecord(graphContext.diagnostics) ? graphContext.diagnostics : {}
  const suppressedCount = Number(diagnostics.suppressed_relation_count ?? diagnostics.suppressed_relations ?? 0) || 0
  const provider = report?.provider ?? 'deterministic-local'
  const model = report?.model || 'default'

  function requestBody(activeMode = mode) {
    const currentDepth = graphDepth(graphDepthValue, preferences.graph_depth)
    const currentWeight = clampNumber(graphWeight, preferences.graph_weight, 0, 1)
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
      candidate_k: preferences.candidate_k,
      reranker_provider: preferences.reranker_provider,
      reranker_model: preferences.reranker_model,
      graph_weight: currentWeight,
      graph_depth: currentDepth,
    }
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault()
    if (!selectedKb || !query.trim()) return
    try {
      const result = await search.mutateAsync(requestBody())
      setMessage(`Search completed in ${mode}: ${result.total_results} results.`)
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
      graph_weight: clampNumber(graphWeight, preferences.graph_weight, 0, 1),
      graph_depth: graphDepth(graphDepthValue, preferences.graph_depth),
    }
    try {
      await savePreferences.mutateAsync({ kbId: selectedKbId, preferences: payload })
      setModeOverride(payload.mode)
      setGraphWeightOverride(String(payload.graph_weight))
      setGraphDepthOverride(String(payload.graph_depth))
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
        <MetricCard label="Graph context" value={matchedEntities.length + relationPaths.length} sub="entities + relation paths" tone={relationPaths.length ? 'ok' : 'info'} />
        <MetricCard label="Suppressed" value={suppressedCount} sub="feedback-aware paths" tone={suppressedCount ? 'warn' : 'ok'} />
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
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
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

        <Panel title="Graph Context" description={report ? `${matchedEntities.length} entities, ${relationPaths.length} paths.` : 'No graph context loaded.'}>
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
            </div>
          </div>
        </Panel>
      </div>
    </ConsolePage>
  )
}
