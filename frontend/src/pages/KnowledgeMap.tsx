import { useState } from 'react'
import { useKnowledgeBases, useKnowledgeMap } from '../api/hooks'

type KnowledgeBase = { id: string; name: string }

type KMNode = {
  id: string
  kind: 'document' | 'entity'
  label: string
  uri?: string
  entity_type?: string
  entity_count?: number | null
  mentions?: number | null
  document_count?: number | null
  topics?: string[]
  metadata?: Record<string, unknown>
}

type KMEdge = {
  id: string
  source: string
  target: string
  relationship: string
  strength: number
  shared_entities?: string[]
  document_count?: number | null
  metadata?: Record<string, unknown>
}

type TopicCoverage = {
  topic: string
  document_count: number
  coverage_pct: number
  document_ids?: string[]
}

type KMStats = {
  total_versions?: number
  completed?: number
  missing?: number
  stale?: number
  failed?: number
  included_documents?: number
  document_nodes?: number
  entity_nodes?: number
  document_relationship_edges?: number
  mention_edges?: number
  co_mention_edges?: number
  cross_document_entity_count?: number
  isolated_document_count?: number
}

type KnowledgeMapResult = {
  schema_version?: string
  generated_at?: string
  knowledge_base_id?: string
  knowledge_base?: string
  profile_id?: string
  status?: string
  nodes?: KMNode[]
  edges?: KMEdge[]
  topic_coverage?: TopicCoverage[]
  stats?: KMStats
  limitations?: string[]
}

function statusChipClass(status: string | undefined) {
  if (status === 'ready') return 'text-emerald-700 bg-emerald-50 border-emerald-200'
  if (status === 'limited') return 'text-amber-700 bg-amber-50 border-amber-200'
  return 'text-gray-500 bg-gray-100 border-gray-200'
}

function statusLabel(status: string | undefined) {
  if (status === 'ready') return 'Ready'
  if (status === 'limited') return 'Limited'
  if (status === 'no_understanding') return 'No understanding data'
  if (status === 'empty_kb') return 'Empty knowledge base'
  return status ?? '—'
}

function filenameFromUri(uri: string | undefined): string {
  if (!uri) return '—'
  const parts = uri.split('/')
  return parts[parts.length - 1] || uri
}

function StatCard({ label, value }: { label: string; value: number | string | undefined }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[110px]">
      <div className="text-[10px] font-bold uppercase text-gray-400 whitespace-nowrap">{label}</div>
      <div className="text-base font-bold text-gray-700">{value ?? '—'}</div>
    </div>
  )
}

export default function KnowledgeMap() {
  const { data: kbList, isLoading: kbLoading } = useKnowledgeBases()
  const kbs = (kbList ?? []) as KnowledgeBase[]

  const [selectedKbId, setSelectedKbId] = useState<string | null>(null)

  const { data: rawData, isLoading: mapLoading } = useKnowledgeMap(selectedKbId)
  const mapData = rawData as KnowledgeMapResult | undefined

  const nodes = mapData?.nodes ?? []
  const edges = mapData?.edges ?? []
  const topicCoverage = (mapData?.topic_coverage ?? []).slice().sort(
    (a, b) => b.document_count - a.document_count
  )
  const stats = mapData?.stats
  const limitations = mapData?.limitations ?? []
  const status = mapData?.status

  const documentNodes = nodes.filter((n) => n.kind === 'document')
  const entityNodes = nodes
    .filter((n) => n.kind === 'entity')
    .slice()
    .sort((a, b) => (b.mentions ?? 0) - (a.mentions ?? 0))
  const docRelEdges = edges.filter((e) => e.relationship === 'shares_entities')

  // Build a node id→label map for edge display
  const nodeById = new Map(nodes.map((n) => [n.id, n]))

  const isEmptyOrNoUnderstanding =
    status === 'empty_kb' || status === 'no_understanding'

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-lg font-bold text-gray-900">Knowledge Map</h1>
        <p className="text-gray-500 text-sm mt-0.5">Cross-document entity relationship graph</p>
      </div>

      {/* KB selector */}
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={selectedKbId ?? ''}
          onChange={(e) => setSelectedKbId(e.target.value || null)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 min-w-[220px]"
          disabled={kbLoading}
        >
          <option value="">Select a knowledge base…</option>
          {kbs.map((kb) => (
            <option key={kb.id} value={kb.id}>
              {kb.name}
            </option>
          ))}
        </select>

        {mapData && status && (
          <span
            className={`text-[11px] font-bold px-2 py-0.5 rounded border ${statusChipClass(status)}`}
          >
            {statusLabel(status)}
          </span>
        )}
      </div>

      {/* No KB selected */}
      {!selectedKbId && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
          <div className="text-sm text-gray-500">Select a knowledge base to view its knowledge map.</div>
        </div>
      )}

      {/* Loading */}
      {selectedKbId && mapLoading && (
        <div className="text-gray-400 text-sm">Building knowledge map…</div>
      )}

      {/* Empty / no understanding */}
      {selectedKbId && !mapLoading && isEmptyOrNoUnderstanding && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center">
          <div className="text-sm font-medium text-gray-600">{statusLabel(status)}</div>
          <div className="text-xs text-gray-400 mt-1">
            {status === 'empty_kb'
              ? 'Upload documents to this knowledge base to generate a knowledge map.'
              : 'Run an understanding pipeline to generate entity relationships.'}
          </div>
        </div>
      )}

      {/* Data sections */}
      {selectedKbId && !mapLoading && mapData && !isEmptyOrNoUnderstanding && (
        <>
          {/* Stats cards */}
          {stats && (
            <div className="flex gap-3 flex-wrap">
              <StatCard label="Document Nodes" value={stats.document_nodes} />
              <StatCard label="Entity Nodes" value={stats.entity_nodes} />
              <StatCard label="Doc↔Doc Edges" value={stats.document_relationship_edges} />
              <StatCard label="Cross-doc Entities" value={stats.cross_document_entity_count} />
              <StatCard label="Isolated Docs" value={stats.isolated_document_count} />
            </div>
          )}

          {/* Limitations */}
          {limitations.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
              <div className="text-xs font-bold text-amber-700 uppercase tracking-wider mb-2">
                Limitations
              </div>
              <ul className="space-y-1">
                {limitations.map((lim, i) => (
                  <li key={i} className="text-sm text-amber-800 flex items-start gap-1.5">
                    <span className="mt-0.5 shrink-0">&#9679;</span>
                    <span>{lim}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Topic Coverage */}
          {topicCoverage.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-gray-700 mb-2">Topic Coverage</h2>
              <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[1fr_auto_auto] gap-4 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                  <div>Topic</div>
                  <div className="text-right">Documents</div>
                  <div className="text-right w-24">Coverage</div>
                </div>
                {topicCoverage.map((tc) => (
                  <div
                    key={tc.topic}
                    className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[1fr_auto_auto] gap-4 items-center"
                  >
                    <div className="text-sm text-gray-700 capitalize">{tc.topic}</div>
                    <div className="text-sm text-gray-700 text-right">{tc.document_count}</div>
                    <div className="text-sm text-gray-700 text-right w-24">
                      {tc.coverage_pct.toFixed(1)}%
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Document Nodes */}
          {documentNodes.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-gray-700 mb-2">
                Document Nodes ({documentNodes.length})
              </h2>
              <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[1fr_2fr_auto] gap-4 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                  <div>Label</div>
                  <div>URI</div>
                  <div className="text-right">Topics</div>
                </div>
                {documentNodes.map((node) => (
                  <div
                    key={node.id}
                    className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[1fr_2fr_auto] gap-4 items-start"
                  >
                    <div className="text-sm text-gray-700 truncate font-medium">
                      {filenameFromUri(node.uri) || node.label}
                    </div>
                    <div className="text-xs font-mono text-gray-400 truncate" title={node.uri}>
                      {node.uri ?? '—'}
                    </div>
                    <div className="text-sm text-gray-700 text-right">
                      {node.topics?.length ?? 0}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Entity Nodes */}
          {entityNodes.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-gray-700 mb-2">
                Entity Nodes ({entityNodes.length})
              </h2>
              <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[1fr_auto_auto_auto] gap-4 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                  <div>Entity</div>
                  <div className="text-right">Type</div>
                  <div className="text-right">Mentions</div>
                  <div className="text-right">In N Docs</div>
                </div>
                {entityNodes.map((node) => (
                  <div
                    key={node.id}
                    className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[1fr_auto_auto_auto] gap-4 items-center"
                  >
                    <div className="text-sm text-gray-700 font-medium">{node.label}</div>
                    <div className="text-right">
                      {node.entity_type ? (
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
                          {node.entity_type}
                        </span>
                      ) : (
                        <span className="text-sm text-gray-400">—</span>
                      )}
                    </div>
                    <div className="text-sm text-gray-700 text-right">{node.mentions ?? '—'}</div>
                    <div className="text-sm text-gray-700 text-right">
                      {node.document_count ?? '—'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Document Relationships */}
          {docRelEdges.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-gray-700 mb-2">
                Document Relationships ({docRelEdges.length})
              </h2>
              <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 grid grid-cols-[1fr_auto_1fr_auto_2fr] gap-3 text-[10px] font-bold uppercase tracking-wider text-gray-400">
                  <div>Source</div>
                  <div></div>
                  <div>Target</div>
                  <div className="text-right">Strength</div>
                  <div>Shared Entities</div>
                </div>
                {docRelEdges.map((edge) => {
                  const srcLabel =
                    filenameFromUri(nodeById.get(edge.source)?.uri) ||
                    nodeById.get(edge.source)?.label ||
                    edge.source
                  const tgtLabel =
                    filenameFromUri(nodeById.get(edge.target)?.uri) ||
                    nodeById.get(edge.target)?.label ||
                    edge.target
                  const sharedEntities = edge.shared_entities ?? []
                  const displayEntities = sharedEntities.slice(0, 5)
                  const extraCount = sharedEntities.length - displayEntities.length
                  return (
                    <div
                      key={edge.id}
                      className="px-4 py-2.5 border-b border-gray-100 last:border-0 grid grid-cols-[1fr_auto_1fr_auto_2fr] gap-3 items-center"
                    >
                      <div className="text-xs text-gray-700 truncate font-medium" title={srcLabel}>
                        {srcLabel}
                      </div>
                      <div className="text-gray-400 text-xs">&#8594;</div>
                      <div className="text-xs text-gray-700 truncate font-medium" title={tgtLabel}>
                        {tgtLabel}
                      </div>
                      <div className="text-sm text-gray-700 text-right whitespace-nowrap">
                        {edge.strength.toFixed(2)}
                      </div>
                      <div className="text-xs text-gray-500">
                        {displayEntities.join(', ')}
                        {extraCount > 0 && (
                          <span className="text-gray-400"> +{extraCount} more</span>
                        )}
                        {displayEntities.length === 0 && '—'}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
