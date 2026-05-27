import { useMemo, useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, MetricCard, Panel, StatusPill } from '../components/console'

type Entity = {
  id: string
  name: string
  type: string
  mentions: number
  documents: number
  confidence: string
}

type Relation = {
  id: string
  subject: string
  predicate: string
  object: string
  evidence: number
  status: 'accepted' | 'needs review'
}

type Claim = {
  id: string
  claim: string
  source: string
  confidence: string
  status: 'verified' | 'review'
}

const ENTITIES: Entity[] = [
  { id: 'ent-retention', name: 'Retention policy', type: 'policy', mentions: 42, documents: 7, confidence: '0.94' },
  { id: 'ent-sanitizer', name: 'Processing sanitizer', type: 'component', mentions: 31, documents: 5, confidence: '0.91' },
  { id: 'ent-graph', name: 'Graph retrieval', type: 'capability', mentions: 28, documents: 4, confidence: '0.89' },
  { id: 'ent-voyage', name: 'Voyage embeddings', type: 'provider', mentions: 16, documents: 3, confidence: '0.86' },
]

const RELATIONS: Relation[] = [
  { id: 'rel-1', subject: 'Retention policy', predicate: 'governs', object: 'Artifact cleanup', evidence: 6, status: 'accepted' },
  { id: 'rel-2', subject: 'Processing sanitizer', predicate: 'redacts', object: 'Sensitive preview fields', evidence: 9, status: 'accepted' },
  { id: 'rel-3', subject: 'Graph retrieval', predicate: 'augments', object: 'Hybrid search ranking', evidence: 4, status: 'needs review' },
  { id: 'rel-4', subject: 'Voyage embeddings', predicate: 'powers', object: 'Production vector index', evidence: 3, status: 'accepted' },
]

const CLAIMS: Claim[] = [
  { id: 'claim-1', claim: 'Graph retrieval should be opt-in per knowledge base.', source: 'kg-lite-graph-retrieval-spec.md', confidence: '0.92', status: 'verified' },
  { id: 'claim-2', claim: 'Sanitizer drift reports are retained as operational artifacts.', source: 'sanitizer-drift-history-spec.md', confidence: '0.88', status: 'verified' },
  { id: 'claim-3', claim: 'Local pilot can run with deterministic providers.', source: 'local-pilot-spec.md', confidence: '0.81', status: 'review' },
]

const EVIDENCE = {
  'rel-1': [
    'Retention applies to audit artifacts, export bundles, and generated summaries.',
    'Cleanup jobs emit audit records before destructive artifact removal.',
  ],
  'rel-2': [
    'Preview sanitization is enforced across markdown, HTML, CSV, and plaintext fixtures.',
    'Cross-layer sanitizer contracts prevent unsafe raw text from escaping into UI previews.',
  ],
  'rel-3': [
    'Graph evidence chunks are merged with dense retrieval candidates before reranking.',
    'KB-level graph preferences control default depth and graph weight.',
  ],
  'rel-4': [
    'Voyage embedding provider is used for high-quality retrieval baselines.',
    'Local fallback providers remain available for air-gapped smoke tests.',
  ],
}

export default function KnowledgeMap() {
  const [selectedRelationId, setSelectedRelationId] = useState(RELATIONS[0].id)
  const [feedback, setFeedback] = useState('No feedback submitted.')
  const [suppressedRelationId, setSuppressedRelationId] = useState<string | null>('rel-3')
  const [depth, setDepth] = useState('2')
  const [weight, setWeight] = useState('0.35')
  const [mode, setMode] = useState('hybrid_graph')
  const selectedRelation = RELATIONS.find((relation) => relation.id === selectedRelationId) ?? RELATIONS[0]
  const suppressedRelation = RELATIONS.find((relation) => relation.id === suppressedRelationId)
  const selectedEvidence = useMemo(() => EVIDENCE[selectedRelation.id as keyof typeof EVIDENCE] ?? [], [selectedRelation])

  return (
    <ConsolePage
      title="Knowledge Map"
      description="Interactive KG Lite prototype for entities, relations, claims, evidence, relation feedback, and KB-level graph retrieval preferences."
      actions={<Button variant="secondary" onClick={() => setFeedback('KG rebuild queued for handbook workspace.')}>Rebuild KG</Button>}
    >
      {feedback && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{feedback}</div>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard label="Entities" value={ENTITIES.length} sub="cross-document" />
        <MetricCard label="Relations" value={RELATIONS.length} sub="with evidence" />
        <MetricCard label="Claims" value={CLAIMS.length} sub="extracted facts" />
        <MetricCard label="Graph depth" value={depth} sub="KB default" />
        <MetricCard label="Graph weight" value={weight} sub="retrieval blend" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Panel title="Relation explorer" description="Select a relation to inspect evidence and submit feedback.">
          <DataTable
            rows={RELATIONS}
            getKey={(row) => row.id}
            onRowClick={(row) => setSelectedRelationId(row.id)}
            columns={[
              { key: 'subject', label: 'Subject', render: (row) => <div className="font-medium text-ink">{row.subject}</div> },
              { key: 'predicate', label: 'Relation', render: (row) => <span className="font-mono text-xs text-slate-600">{row.predicate}</span> },
              { key: 'object', label: 'Object', render: (row) => row.object },
              { key: 'evidence', label: 'Evidence', align: 'right', render: (row) => row.evidence },
              { key: 'status', label: 'Status', render: (row) => (
                suppressedRelationId === row.id
                  ? <StatusPill tone="warn">suppressed</StatusPill>
                  : <StatusPill tone={row.status === 'accepted' ? 'ok' : 'warn'}>{row.status}</StatusPill>
              ) },
            ]}
          />
        </Panel>

        <Panel title="Evidence detail" description={`${selectedRelation.subject} ${selectedRelation.predicate} ${selectedRelation.object}`}>
          <div className="space-y-3">
            {selectedEvidence.map((item) => (
              <div key={item} className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm text-slate-700">
                {item}
              </div>
            ))}
            <div className="flex flex-wrap gap-2 pt-1">
              <Button variant="secondary" onClick={() => {
                setSuppressedRelationId(null)
                setFeedback(`Accepted relation ${selectedRelation.id}; retrieval suppression cleared.`)
              }}>Accept</Button>
              <Button variant="secondary" onClick={() => setFeedback(`Flagged ${selectedRelation.id} for curator review.`)}>Needs review</Button>
              <Button variant="secondary" onClick={() => {
                setSuppressedRelationId(selectedRelation.id)
                setFeedback(`Hidden ${selectedRelation.id} from graph retrieval until reviewed.`)
              }}>Hide from retrieval</Button>
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel title="Entities" description="High-signal entities extracted from understanding runs.">
          <DataTable
            rows={ENTITIES}
            getKey={(row) => row.id}
            columns={[
              { key: 'name', label: 'Entity', render: (row) => <div><div className="font-medium text-ink">{row.name}</div><div className="text-xs text-muted">{row.type}</div></div> },
              { key: 'mentions', label: 'Mentions', align: 'right', render: (row) => row.mentions },
              { key: 'documents', label: 'Docs', align: 'right', render: (row) => row.documents },
              { key: 'confidence', label: 'Confidence', render: (row) => <span className="font-mono text-xs">{row.confidence}</span> },
            ]}
          />
        </Panel>

        <Panel title="Claims" description="Claim-level facts are shown separately from entity relations.">
          <DataTable
            rows={CLAIMS}
            getKey={(row) => row.id}
            columns={[
              { key: 'claim', label: 'Claim', render: (row) => <div className="max-w-xl text-sm text-ink">{row.claim}</div> },
              { key: 'source', label: 'Source', render: (row) => <span className="font-mono text-xs text-slate-600">{row.source}</span> },
              { key: 'confidence', label: 'Confidence', render: (row) => row.confidence },
              { key: 'status', label: 'Status', render: (row) => <StatusPill tone={row.status === 'verified' ? 'ok' : 'warn'}>{row.status}</StatusPill> },
            ]}
          />
        </Panel>
      </div>

      <Panel title="Retrieval preferences" description="Prototype for KB-level graph retrieval defaults before wiring the real preference API.">
        <div className="grid gap-4 md:grid-cols-3">
          <label className="space-y-1">
            <span className="text-xs font-medium text-slate-600">Default retrieval mode</span>
            <select value={mode} onChange={(event) => setMode(event.target.value)} className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm">
              <option value="dense">dense</option>
              <option value="hybrid">hybrid</option>
              <option value="graph">graph</option>
              <option value="hybrid_graph">hybrid_graph</option>
              <option value="graph_rerank">graph_rerank</option>
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-slate-600">Graph depth</span>
            <input value={depth} onChange={(event) => setDepth(event.target.value)} className="w-full rounded-lg border border-line px-3 py-2 text-sm" />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-slate-600">Graph weight</span>
            <input value={weight} onChange={(event) => setWeight(event.target.value)} className="w-full rounded-lg border border-line px-3 py-2 text-sm" />
          </label>
        </div>
        <div className="mt-4 flex justify-end">
          <Button onClick={() => setFeedback(`Saved graph preferences: ${mode}, depth ${depth}, weight ${weight}.`)}>Save preferences</Button>
        </div>
      </Panel>

      <Panel title="Retrieval impact" description="Relation feedback immediately changes graph retrieval context in the prototype.">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted">Accepted paths</div>
            <div className="mt-2 text-sm text-slate-700">Retention policy &rarr; governs &rarr; Artifact cleanup</div>
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
            <div className="text-xs font-semibold uppercase tracking-wider text-amber-700">Suppressed path</div>
            <div className="mt-2 text-sm text-amber-800">
              {suppressedRelation ? `${suppressedRelation.subject} -> ${suppressedRelation.predicate} -> ${suppressedRelation.object}` : 'None'}
            </div>
          </div>
          <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted">Runbook state</div>
            <div className="mt-2 text-sm text-slate-700">Graph console rehearsal ready</div>
          </div>
        </div>
      </Panel>
    </ConsolePage>
  )
}
