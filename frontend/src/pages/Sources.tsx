import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'
import { SchemaModal, type SchemaSubmit } from '../components/SchemaModal'
import { SOURCE_SCHEMAS } from './consoleSchemas'

type SourceRow = {
  id: string
  name: string
  type: string
  scope: string
  auth: string
  lastSync: string
  status: 'healthy' | 'warning'
}

const INITIAL_SOURCES: SourceRow[] = [
  { id: 'src-s3-prod', name: 'prod-docs-s3', type: 'S3 / MinIO', scope: 's3://prod-rag/docs/**', auth: 'env refs', lastSync: '12m ago', status: 'healthy' },
  { id: 'src-web-docs', name: 'public-docs', type: 'Web crawler', scope: 'https://docs.ragrig.dev/**', auth: 'none', lastSync: '47m ago', status: 'healthy' },
  { id: 'src-github', name: 'ragrig-repo', type: 'GitHub repository', scope: 'docs/**, README.md', auth: 'env:GITHUB_TOKEN', lastSync: '2h ago', status: 'warning' },
]

export default function Sources() {
  const [sources, setSources] = useState(INITIAL_SOURCES)
  const [showModal, setShowModal] = useState(false)
  const [message, setMessage] = useState('')

  const addSource = (payload: SchemaSubmit) => {
    const name = payload.values.bucket || payload.values.repo || payload.values.seedUrl || payload.label
    const scope = payload.values.prefix || payload.values.paths || payload.values.includePattern || payload.values.seedUrl || 'configured scope'
    setSources((current) => [
      {
        id: `src-${Date.now()}`,
        name,
        type: payload.label,
        scope,
        auth: payload.values.accessKeyRef || payload.values.tokenRef || 'none',
        lastSync: 'not synced',
        status: 'healthy',
      },
      ...current,
    ])
    setMessage(`${payload.label} source created. Use the row action when you are ready to ingest it.`)
    setShowModal(false)
  }

  return (
    <ConsolePage
      title="Sources"
      description="Input connectors are configured, validated, and synced from their own row. There is no global sync action."
      actions={<Button onClick={() => setShowModal(true)}>New source</Button>}
    >
      <Panel title="Input connectors" description="Each connector exposes only the fields required by its selected type.">
        {message && <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
        <DataTable
          rows={sources}
          getKey={(row) => row.id}
          columns={[
            { key: 'name', label: 'Source', render: (row) => <div><div className="font-medium text-ink">{row.name}</div><div className="text-xs text-muted">{row.type}</div></div> },
            { key: 'scope', label: 'Scope', render: (row) => <span className="font-mono text-xs text-slate-600">{row.scope}</span> },
            { key: 'auth', label: 'Auth', render: (row) => <span className="font-mono text-xs text-slate-600">{row.auth}</span> },
            { key: 'lastSync', label: 'Last sync', render: (row) => row.lastSync },
            { key: 'status', label: 'Status', render: (row) => <StatusPill tone={row.status === 'healthy' ? 'ok' : 'warn'}>{row.status}</StatusPill> },
            { key: 'actions', label: 'Actions', align: 'right', render: (row) => <button onClick={() => setMessage(`Sync queued for ${row.name}`)} className="rounded-lg border border-line px-2 py-1 text-xs font-medium text-brand hover:bg-blue-50">Sync now</button> },
          ]}
        />
      </Panel>

      {showModal && (
        <SchemaModal
          title="New source"
          schemas={SOURCE_SCHEMAS}
          submitLabel="Create source"
          onClose={() => setShowModal(false)}
          onSubmit={addSource}
        />
      )}
    </ConsolePage>
  )
}
