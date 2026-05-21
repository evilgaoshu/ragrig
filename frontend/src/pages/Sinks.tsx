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
}

const INITIAL_SINKS: SinkRow[] = [
  { id: 'sink-agent', name: 'agent-access-export', type: 'Webhook sink', target: 'https://agent.example.com/ingest', format: 'ndjson', delivery: 'retry x3', status: 'ready' },
  { id: 'sink-archive', name: 'daily-object-export', type: 'Object storage export', target: 's3://rag-exports/prod/', format: 'parquet', delivery: 'daily', status: 'ready' },
]

export default function Sinks() {
  const [sinks, setSinks] = useState(INITIAL_SINKS)
  const [showModal, setShowModal] = useState(false)
  const [message, setMessage] = useState('')

  const addSink = (payload: SchemaSubmit) => {
    const target = payload.values.endpoint || payload.values.bucket || 'configured target'
    setSinks((current) => [
      {
        id: `sink-${Date.now()}`,
        name: payload.values.bucket || payload.values.endpoint || payload.label,
        type: payload.label,
        target,
        format: payload.values.format || 'json',
        delivery: payload.values.retention || payload.values.batchSize || 'default',
        status: 'ready',
      },
      ...current,
    ])
    setMessage(`${payload.label} sink created.`)
    setShowModal(false)
  }

  return (
    <ConsolePage
      title="Sinks"
      description="Output destinations for chunks, artifacts, and pipeline results."
      actions={<Button onClick={() => setShowModal(true)}>New sink</Button>}
    >
      <Panel title="Output connectors" description="Delivery tests are contextual to the selected sink.">
        {message && <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
        <DataTable
          rows={sinks}
          getKey={(row) => row.id}
          columns={[
            { key: 'name', label: 'Sink', render: (row) => <div><div className="font-medium text-ink">{row.name}</div><div className="text-xs text-muted">{row.type}</div></div> },
            { key: 'target', label: 'Target', render: (row) => <span className="font-mono text-xs text-slate-600">{row.target}</span> },
            { key: 'format', label: 'Format', render: (row) => row.format },
            { key: 'delivery', label: 'Delivery', render: (row) => row.delivery },
            { key: 'status', label: 'Status', render: (row) => <StatusPill tone={row.status === 'ready' ? 'ok' : 'neutral'}>{row.status}</StatusPill> },
            { key: 'actions', label: 'Actions', align: 'right', render: (row) => <button onClick={() => setMessage(`Delivery test queued for ${row.name}`)} className="rounded-lg border border-line px-2 py-1 text-xs font-medium text-brand hover:bg-blue-50">Test delivery</button> },
          ]}
        />
      </Panel>

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
