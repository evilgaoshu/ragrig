import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'
import { SchemaModal, type SchemaSubmit } from '../components/SchemaModal'
import { SINK_SCHEMAS } from './consoleSchemas'

type SinkRow = {
  id: string
  name: string
  type: string
  target: string
  format: string
  delivery: string
  status: 'ready' | 'paused'
  includes: string
}

const INITIAL_SINKS: SinkRow[] = [
  { id: 'sink-agent', name: 'agent-access-export', type: 'Webhook sink', target: 'https://agent.example.com/ingest', format: 'ndjson', delivery: 'retry x3', status: 'ready', includes: 'answer traces, citations, retrieval artifacts' },
  { id: 'sink-archive', name: 'daily-object-export', type: 'Object storage export', target: 's3://rag-exports/prod/', format: 'parquet', delivery: 'daily', status: 'ready', includes: 'chunks, embeddings metadata, quality reports' },
]

export default function Sinks() {
  const [sinks, setSinks] = useState(INITIAL_SINKS)
  const [selectedSinkId, setSelectedSinkId] = useState(INITIAL_SINKS[0].id)
  const [showModal, setShowModal] = useState(false)
  const [message, setMessage] = useState('')
  const selectedSink = sinks.find((sink) => sink.id === selectedSinkId) ?? sinks[0]

  const addSink = (payload: SchemaSubmit) => {
    const target = payload.values.endpoint || payload.values.bucket || 'configured target'
    const id = `sink-${Date.now()}`
    setSinks((current) => [
      {
        id,
        name: payload.values.bucket || payload.values.endpoint || payload.label,
        type: payload.label,
        target,
        format: payload.values.format || 'json',
        delivery: payload.values.retention || payload.values.batchSize || 'default',
        status: 'ready',
        includes: 'configured export payload',
      },
      ...current,
    ])
    setSelectedSinkId(id)
    setMessage(`${payload.label} sink created.`)
    setShowModal(false)
  }

  return (
    <ConsolePage
      title="Sinks"
      description="Output destinations for chunks, artifacts, and pipeline results."
      actions={<Button onClick={() => setShowModal(true)}>New sink</Button>}
    >
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Panel title="Output connectors" description="Delivery tests and exports are contextual to the selected sink.">
          <DataTable
            rows={sinks}
            getKey={(row) => row.id}
            onRowClick={(row) => setSelectedSinkId(row.id)}
            columns={[
              { key: 'name', label: 'Sink', render: (row) => <div><div className="font-medium text-ink">{row.name}</div><div className="text-xs text-muted">{row.type}</div></div> },
              { key: 'target', label: 'Target', render: (row) => <span className="font-mono text-xs text-slate-600">{row.target}</span> },
              { key: 'format', label: 'Format', render: (row) => row.format },
              { key: 'delivery', label: 'Delivery', render: (row) => row.delivery },
              { key: 'status', label: 'Status', render: (row) => <StatusPill tone={row.status === 'ready' ? 'ok' : 'neutral'}>{row.status}</StatusPill> },
              { key: 'actions', label: 'Actions', align: 'right', render: (row) => <button onClick={() => setMessage(`Delivery test queued for ${row.name}`)} className="rounded-lg border border-line px-2 py-1 text-xs font-medium text-brand hover:bg-blue-50">Test</button> },
            ]}
          />
        </Panel>
        <Panel
          title={`${selectedSink.name} detail`}
          description={selectedSink.target}
          actions={<Button onClick={() => setMessage(`Dry run export generated for ${selectedSink.name}.`)}>Dry run export</Button>}
        >
          <div className="space-y-3">
            <div className="rounded-lg border border-line bg-white p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted">Includes</div>
              <div className="mt-2 text-sm text-slate-700">{selectedSink.includes}</div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">Format: {selectedSink.format}</div>
              <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">Delivery: {selectedSink.delivery}</div>
              <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">Retry: exponential backoff</div>
              <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">Audit: export manifest</div>
            </div>
          </div>
        </Panel>
      </div>

      {showModal && (
        <SchemaModal
          title="New sink"
          schemas={SINK_SCHEMAS}
          submitLabel="Create sink"
          onClose={() => setShowModal(false)}
          onSubmit={addSink}
        />
      )}
    </ConsolePage>
  )
}
