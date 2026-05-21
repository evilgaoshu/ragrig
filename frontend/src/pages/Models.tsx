import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'
import { SchemaModal, type SchemaSubmit } from '../components/SchemaModal'
import { PROVIDER_SCHEMAS } from './consoleSchemas'

type ProviderRow = {
  id: string
  name: string
  kind: string
  models: string
  capabilities: string
  status: 'healthy' | 'needs key'
}

const INITIAL_PROVIDERS: ProviderRow[] = [
  { id: 'openai', name: 'openai-prod', kind: 'OpenAI-compatible', models: 'gpt-4.1-mini · text-embedding-3-small', capabilities: 'chat, embed', status: 'healthy' },
  { id: 'voyage', name: 'voyage-retrieval', kind: 'Voyage embeddings', models: 'voyage-3-large', capabilities: 'embed', status: 'healthy' },
  { id: 'ollama', name: 'local-pilot', kind: 'Ollama local', models: 'llama3.1 · nomic-embed-text', capabilities: 'chat, embed', status: 'needs key' },
]

export default function Models() {
  const [providers, setProviders] = useState(INITIAL_PROVIDERS)
  const [showModal, setShowModal] = useState(false)
  const [message, setMessage] = useState('')

  const addProvider = (payload: SchemaSubmit) => {
    setProviders((current) => [
      {
        id: `provider-${Date.now()}`,
        name: payload.values.chatModel || payload.values.model || payload.label,
        kind: payload.label,
        models: [payload.values.chatModel, payload.values.embeddingModel, payload.values.model].filter(Boolean).join(' · ') || 'configured model',
        capabilities: payload.schemaId === 'voyage' ? 'embed' : 'chat, embed',
        status: 'healthy',
      },
      ...current,
    ])
    setMessage(`${payload.label} provider created.`)
    setShowModal(false)
  }

  return (
    <ConsolePage
      title="AI Providers"
      description="Model providers, embedding profiles, fallbacks, and health state."
      actions={<Button onClick={() => setShowModal(true)}>New provider</Button>}
    >
      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <Panel title="Providers" description="Provider-specific fields are shown at creation time.">
          {message && <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
          <DataTable
            rows={providers}
            getKey={(row) => row.id}
            columns={[
              { key: 'name', label: 'Provider', render: (row) => <div><div className="font-medium text-ink">{row.name}</div><div className="text-xs text-muted">{row.kind}</div></div> },
              { key: 'models', label: 'Models', render: (row) => <span className="font-mono text-xs text-slate-600">{row.models}</span> },
              { key: 'capabilities', label: 'Capabilities', render: (row) => row.capabilities },
              { key: 'status', label: 'Status', render: (row) => <StatusPill tone={row.status === 'healthy' ? 'ok' : 'warn'}>{row.status}</StatusPill> },
              { key: 'actions', label: 'Actions', align: 'right', render: (row) => <button onClick={() => setMessage(`Health check queued for ${row.name}`)} className="rounded-lg border border-line px-2 py-1 text-xs font-medium text-brand hover:bg-blue-50">Check health</button> },
            ]}
          />
        </Panel>
        <Panel title="Routing policy" description="Used by answer generation and enrichment steps.">
          <div className="space-y-3 text-sm">
            <div className="rounded-lg border border-line bg-blue-50/50 p-3">
              <div className="font-medium text-ink">Answer generation</div>
              <div className="mt-1 text-xs text-muted">Primary OpenAI-compatible · fallback local-pilot after 2 failures</div>
            </div>
            <div className="rounded-lg border border-line bg-blue-50/50 p-3">
              <div className="font-medium text-ink">Embedding</div>
              <div className="mt-1 text-xs text-muted">voyage-retrieval for production, local-pilot for air-gapped smoke tests</div>
            </div>
          </div>
        </Panel>
      </div>

      {showModal && (
        <SchemaModal
          title="New AI provider"
          schemas={PROVIDER_SCHEMAS}
          submitLabel="Create provider"
          onClose={() => setShowModal(false)}
          onSubmit={addProvider}
        />
      )}
    </ConsolePage>
  )
}
