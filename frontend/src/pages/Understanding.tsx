import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'

const RUNS = [
  { id: 'u-182', kb: 'handbook', entities: 384, relations: 921, status: 'completed', delta: '+18 relations' },
  { id: 'u-181', kb: 'support-faq', entities: 126, relations: 244, status: 'completed', delta: 'stable' },
  { id: 'u-180', kb: 'engineering', entities: 712, relations: 1881, status: 'review', delta: '3 conflicts' },
]

export default function Understanding() {
  const [selectedId, setSelectedId] = useState(RUNS[0].id)
  const [message, setMessage] = useState('')
  const selected = RUNS.find((run) => run.id === selectedId) ?? RUNS[0]

  return (
    <ConsolePage
      title="Understanding"
      description="Document understanding runs, entity extraction, relation maps, and export diffs."
      actions={<Button onClick={() => setMessage('Understanding run queued for selected knowledge base.')}>New run</Button>}
    >
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <Panel title="Understanding runs" description="Click a run to inspect its export diff and graph preview.">
          <DataTable
            rows={RUNS}
            getKey={(row) => row.id}
            onRowClick={(row) => setSelectedId(row.id)}
            columns={[
              { key: 'id', label: 'Run', render: (row) => <span className="font-mono text-xs">{row.id}</span> },
              { key: 'kb', label: 'Knowledge base', render: (row) => row.kb },
              { key: 'entities', label: 'Entities', align: 'right', render: (row) => row.entities },
              { key: 'relations', label: 'Relations', align: 'right', render: (row) => row.relations },
              { key: 'delta', label: 'Export diff', render: (row) => row.delta },
              { key: 'status', label: 'Status', render: (row) => <StatusPill tone={row.status === 'review' ? 'warn' : 'ok'}>{row.status}</StatusPill> },
            ]}
          />
        </Panel>
        <Panel
          title={`${selected.id} run detail`}
          description={`${selected.kb} · ${selected.entities} entities · ${selected.relations} relations`}
          actions={<Button variant="secondary" onClick={() => setMessage(`Export diff opened for ${selected.id}.`)}>View diff</Button>}
        >
          <div className="space-y-3">
            {['Policy → owns → Retention rule', 'Connector → emits → Pipeline run', 'Answer → cites → Chunk lineage'].map((edge) => (
              <div key={edge} className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 font-mono text-xs text-slate-700">{edge}</div>
            ))}
            <div className="rounded-lg border border-line bg-white p-3 text-sm text-slate-700">
              Export diff: {selected.delta}. Review suggested before making this run the retrieval default.
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setMessage(`${selected.id} marked as retrieval-ready.`)}>Mark ready</Button>
              <Button variant="secondary" onClick={() => setMessage(`${selected.id} re-run queued with stricter extraction profile.`)}>Re-run</Button>
            </div>
          </div>
        </Panel>
      </div>
    </ConsolePage>
  )
}
