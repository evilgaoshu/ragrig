import { useMemo, useState } from 'react'
import {
  useKnowledgeBases,
  useKnowledgeGraph,
  useRebuildKnowledgeGraph,
  useRetrievalPreferences,
  useSaveRetrievalPreferences,
  useSubmitRelationFeedback,
} from '../api/hooks'
import type { KnowledgeGraphRelation, RelationFeedbackSummary, RetrievalPreferences } from '../api/types'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, MetricCard, Panel, StatusPill } from '../components/console'

const MODES = [
  'dense',
  'hybrid',
  'rerank',
  'hybrid_rerank',
  'graph',
  'hybrid_graph',
  'graph_rerank',
  'hybrid_graph_rerank',
]

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

function formatScore(value: number | null | undefined) {
  return typeof value === 'number' ? value.toFixed(2) : '--'
}

function feedbackSummary(relation: KnowledgeGraphRelation): RelationFeedbackSummary {
  return relation.metadata?.feedback_summary ?? {}
}

function relationStatus(relation: KnowledgeGraphRelation) {
  const summary = feedbackSummary(relation)
  if ((summary.incorrect ?? 0) > 0) return { label: 'suppressed', tone: 'warn' as const }
  if ((summary.needs_review ?? 0) > 0) return { label: 'needs review', tone: 'warn' as const }
  if ((summary.correct ?? 0) > 0) return { label: 'accepted', tone: 'ok' as const }
  return { label: 'unreviewed', tone: 'neutral' as const }
}

function clampNumber(raw: string, fallback: number, min: number, max: number) {
  const value = Number(raw)
  if (!Number.isFinite(value)) return fallback
  return Math.min(max, Math.max(min, value))
}

function graphDepth(raw: string, fallback: number) {
  return Math.round(clampNumber(raw, fallback, 0, 2))
}

export default function KnowledgeMap() {
  const { data: kbs } = useKnowledgeBases()
  const [selectedKbIdOverride, setSelectedKbIdOverride] = useState('')
  const [selectedRelationId, setSelectedRelationId] = useState('')
  const [message, setMessage] = useState('')
  const [depthOverride, setDepthOverride] = useState<string | null>(null)
  const [weightOverride, setWeightOverride] = useState<string | null>(null)
  const [modeOverride, setModeOverride] = useState<string | null>(null)

  const preferredKb = useMemo(() => {
    const items = kbs ?? []
    return items.find((kb) => kb.name === 'local-pilot-demo-rc') ?? items[0] ?? null
  }, [kbs])
  const selectedKbId = selectedKbIdOverride || preferredKb?.id || ''
  const selectedKb = useMemo(() => {
    return (kbs ?? []).find((kb) => kb.id === selectedKbId) ?? null
  }, [kbs, selectedKbId])

  const graphQuery = useKnowledgeGraph(selectedKbId || null)
  const preferencesQuery = useRetrievalPreferences(selectedKbId || null)
  const rebuildGraph = useRebuildKnowledgeGraph()
  const savePreferences = useSaveRetrievalPreferences()
  const submitFeedback = useSubmitRelationFeedback()

  const graph = graphQuery.data
  const entities = graph?.entities ?? []
  const relations = graph?.relations ?? []
  const claims = graph?.claims ?? []
  const selectedRelation = relations.find((relation) => relation.id === selectedRelationId) ?? relations[0] ?? null
  const selectedEvidence = selectedRelation?.evidence ?? []
  const suppressedCount = relations.filter((relation) => (feedbackSummary(relation).incorrect ?? 0) > 0).length
  const stats = graph?.stats
  const savedPreferences = preferencesQuery.data?.preferences
  const mode = modeOverride ?? savedPreferences?.mode ?? DEFAULT_PREFERENCES.mode
  const depth = depthOverride ?? String(savedPreferences?.graph_depth ?? DEFAULT_PREFERENCES.graph_depth)
  const weight = weightOverride ?? String(savedPreferences?.graph_weight ?? DEFAULT_PREFERENCES.graph_weight)

  async function handleRebuild() {
    if (!selectedKbId) return
    try {
      const result = await rebuildGraph.mutateAsync({ kbId: selectedKbId })
      setMessage(`KG rebuild completed: ${result.created ?? 0} created, ${result.skipped ?? 0} skipped.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'KG rebuild failed.')
    }
  }

  async function handleFeedback(verdict: 'correct' | 'incorrect' | 'needs_review') {
    if (!selectedKbId || !selectedRelation) return
    try {
      const result = await submitFeedback.mutateAsync({
        kbId: selectedKbId,
        relationId: selectedRelation.id,
        verdict,
        note: `Console feedback: ${verdict}`,
      })
      setMessage(`Recorded ${verdict} feedback for ${result.relation_id}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Relation feedback failed.')
    }
  }

  async function handleSavePreferences() {
    if (!selectedKbId) return
    const current = preferencesQuery.data?.preferences ?? DEFAULT_PREFERENCES
    const preferences: RetrievalPreferences = {
      ...current,
      mode,
      graph_depth: graphDepth(depth, current.graph_depth),
      graph_weight: clampNumber(weight, current.graph_weight, 0, 1),
    }
    try {
      await savePreferences.mutateAsync({ kbId: selectedKbId, preferences })
      setModeOverride(preferences.mode)
      setDepthOverride(String(preferences.graph_depth))
      setWeightOverride(String(preferences.graph_weight))
      setMessage(`Saved graph preferences for ${selectedKb?.name ?? 'knowledge base'}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Failed to save retrieval preferences.')
    }
  }

  return (
    <ConsolePage
      title="Knowledge Map"
      description="KG Lite entities, relations, claims, evidence, relation feedback, and KB-level graph retrieval preferences."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <select
            id="knowledge-map-kb-select"
            value={selectedKbId}
            onChange={(event) => {
              setSelectedKbIdOverride(event.target.value)
              setSelectedRelationId('')
              setModeOverride(null)
              setDepthOverride(null)
              setWeightOverride(null)
            }}
            className="h-10 rounded-lg border border-line bg-white px-3 text-sm"
          >
            <option value="">Select KB...</option>
            {(kbs ?? []).map((kb) => (
              <option key={kb.id} value={kb.id}>
                {kb.name}
              </option>
            ))}
          </select>
          <Button variant="secondary" onClick={handleRebuild} disabled={!selectedKbId || rebuildGraph.isPending}>
            {rebuildGraph.isPending ? 'Rebuilding...' : 'Rebuild KG'}
          </Button>
        </div>
      }
    >
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard label="Entities" value={stats?.entity_count ?? entities.length} sub="cross-document" />
        <MetricCard label="Relations" value={stats?.relation_count ?? relations.length} sub="with evidence" />
        <MetricCard label="Claims" value={stats?.claim_count ?? claims.length} sub="extracted facts" />
        <MetricCard label="Evidence chunks" value={stats?.graph_evidence_chunk_count ?? 0} sub="graph retrieval" />
        <MetricCard label="Suppressed" value={suppressedCount} sub="feedback-aware paths" tone={suppressedCount ? 'warn' : 'ok'} />
      </div>

      {!selectedKbId ? (
        <Panel title="No knowledge base selected">
          <div className="text-sm text-muted">Create or select a knowledge base to load graph data.</div>
        </Panel>
      ) : graphQuery.isError ? (
        <Panel title="Knowledge graph unavailable">
          <div className="text-sm text-red-600">
            {graphQuery.error instanceof Error ? graphQuery.error.message : 'Failed to load graph data.'}
          </div>
        </Panel>
      ) : !graph && graphQuery.isLoading ? (
        <Panel title="Loading graph">
          <div className="text-sm text-muted">Loading KG data for {selectedKb?.name ?? 'selected KB'}...</div>
        </Panel>
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
            <Panel title="Relation Explorer" description={`${relations.length} relations from ${graph?.knowledge_base ?? selectedKb?.name ?? 'selected KB'}.`}>
              {relations.length ? (
                <DataTable
                  rows={relations}
                  getKey={(row) => row.id}
                  onRowClick={(row) => setSelectedRelationId(row.id)}
                  columns={[
                    { key: 'subject', label: 'Subject', render: (row) => <div className="font-medium text-ink">{row.subject}</div> },
                    { key: 'predicate', label: 'Relation', render: (row) => <span className="font-mono text-xs text-slate-600">{row.predicate}</span> },
                    { key: 'object', label: 'Object', render: (row) => row.object },
                    { key: 'evidence', label: 'Evidence', align: 'right', render: (row) => row.evidence.length },
                    { key: 'confidence', label: 'Conf.', render: (row) => <span className="font-mono text-xs">{formatScore(row.confidence)}</span> },
                    { key: 'status', label: 'Status', render: (row) => {
                      const status = relationStatus(row)
                      return <StatusPill tone={status.tone}>{status.label}</StatusPill>
                    } },
                  ]}
                />
              ) : (
                <div className="text-sm text-muted">No relations have been extracted for this knowledge base.</div>
              )}
            </Panel>

            <Panel
              title="Evidence Detail"
              description={
                selectedRelation
                  ? `${selectedRelation.subject} ${selectedRelation.predicate} ${selectedRelation.object}`
                  : 'No relation selected'
              }
            >
              {selectedRelation ? (
                <div className="space-y-3">
                  {selectedEvidence.length ? (
                    selectedEvidence.map((item) => (
                      <div key={item.id} className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm text-slate-700">
                        <div className="font-mono text-xs text-muted">{item.document_uri}</div>
                        <div className="mt-2 leading-6">{item.text_preview || item.evidence_text}</div>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-lg border border-line bg-white p-3 text-sm text-muted">No evidence chunks recorded.</div>
                  )}
                  <div className="flex flex-wrap gap-2 pt-1">
                    <Button variant="secondary" onClick={() => handleFeedback('correct')} disabled={submitFeedback.isPending}>Accept</Button>
                    <Button variant="secondary" onClick={() => handleFeedback('needs_review')} disabled={submitFeedback.isPending}>Needs Review</Button>
                    <Button variant="secondary" onClick={() => handleFeedback('incorrect')} disabled={submitFeedback.isPending}>Hide From Retrieval</Button>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted">Select a relation to inspect evidence.</div>
              )}
            </Panel>
          </div>

          <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
            <Panel title="Entities" description={`${entities.length} extracted entities.`}>
              {entities.length ? (
                <DataTable
                  rows={entities}
                  getKey={(row) => row.id}
                  columns={[
                    { key: 'name', label: 'Entity', render: (row) => <div><div className="font-medium text-ink">{row.display_name}</div><div className="text-xs text-muted">{row.entity_type}</div></div> },
                    { key: 'mentions', label: 'Mentions', align: 'right', render: (row) => row.mention_count },
                    { key: 'evidence', label: 'Evidence', align: 'right', render: (row) => row.evidence_chunks.length },
                    { key: 'confidence', label: 'Confidence', render: (row) => <span className="font-mono text-xs">{formatScore(row.confidence)}</span> },
                  ]}
                />
              ) : (
                <div className="text-sm text-muted">No entities have been extracted for this knowledge base.</div>
              )}
            </Panel>

            <Panel title="Claims" description={`${claims.length} claim-level facts.`}>
              {claims.length ? (
                <DataTable
                  rows={claims}
                  getKey={(row) => row.id}
                  columns={[
                    { key: 'claim', label: 'Claim', render: (row) => <div className="max-w-xl text-sm text-ink">{row.claim_text}</div> },
                    { key: 'source', label: 'Source', render: (row) => <span className="font-mono text-xs text-slate-600">{row.document_uri}</span> },
                    { key: 'confidence', label: 'Confidence', render: (row) => formatScore(row.confidence) },
                    { key: 'preview', label: 'Evidence', render: (row) => <div className="max-w-md text-xs text-slate-600">{row.text_preview}</div> },
                  ]}
                />
              ) : (
                <div className="text-sm text-muted">No claims have been extracted for this knowledge base.</div>
              )}
            </Panel>
          </div>
        </>
      )}

      <Panel title="Retrieval Preferences" description={preferencesQuery.isFetching ? 'Loading saved preferences...' : 'KB-level graph retrieval defaults.'}>
        <div className="grid gap-4 md:grid-cols-3">
          <label className="space-y-1">
            <span className="text-xs font-medium text-slate-600">Default retrieval mode</span>
            <select
              id="knowledge-map-mode"
              value={mode}
              onChange={(event) => setModeOverride(event.target.value)}
              className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm"
            >
              {MODES.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-slate-600">Graph depth</span>
            <input
              id="knowledge-map-depth"
              type="number"
              min={0}
              max={2}
              value={depth}
              onChange={(event) => setDepthOverride(event.target.value)}
              className="w-full rounded-lg border border-line px-3 py-2 text-sm"
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-slate-600">Graph weight</span>
            <input
              id="knowledge-map-weight"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={weight}
              onChange={(event) => setWeightOverride(event.target.value)}
              className="w-full rounded-lg border border-line px-3 py-2 text-sm"
            />
          </label>
        </div>
        <div className="mt-4 flex justify-end">
          <Button onClick={handleSavePreferences} disabled={!selectedKbId || savePreferences.isPending}>
            {savePreferences.isPending ? 'Saving...' : 'Save Preferences'}
          </Button>
        </div>
      </Panel>
    </ConsolePage>
  )
}
