import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'

const RUNS = [
  { id: 'u-182', kb: 'handbook', entities: 384, relations: 921, status: 'completed', delta: '+18 relations' },
  { id: 'u-181', kb: 'support-faq', entities: 126, relations: 244, status: 'completed', delta: 'stable' },
  { id: 'u-180', kb: 'engineering', entities: 712, relations: 1881, status: 'review', delta: '3 conflicts' },
]

export default function Understanding() {
  return (
    <ConsolePage title="Understanding" description="Document understanding runs, entity extraction, relation maps, and export diffs.">
      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <Panel title="Understanding runs">
          <DataTable
            rows={RUNS}
            getKey={(row) => row.id}
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
        <Panel title="Entity graph preview" description="High-signal entities and relationships from the selected run.">
          <div className="space-y-3">
            {['Policy → owns → Retention rule', 'Connector → emits → Pipeline run', 'Answer → cites → Chunk lineage'].map((edge) => (
              <div key={edge} className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 font-mono text-xs text-slate-700">{edge}</div>
            ))}
          </div>
        </Panel>
      </div>
    </ConsolePage>
  )
}
