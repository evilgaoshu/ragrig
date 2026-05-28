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

type RoleRoute = {
  id: string
  scope: string
  role: string
  answerModel: string
  embeddingModel: string
  fallback: string
  budget: string
}

const INITIAL_PROVIDERS: ProviderRow[] = [
  { id: 'openai', name: 'openai-prod', kind: 'OpenAI-compatible', models: 'gpt-4.1-mini · text-embedding-3-small', capabilities: 'chat, embed', status: 'healthy' },
  { id: 'voyage', name: 'voyage-retrieval', kind: 'Voyage embeddings', models: 'voyage-3-large', capabilities: 'embed', status: 'healthy' },
  { id: 'ollama', name: 'local-pilot', kind: 'Ollama local', models: 'llama3.1 · nomic-embed-text', capabilities: 'chat, embed', status: 'needs key' },
]

const INITIAL_ROLE_ROUTES: RoleRoute[] = [
  { id: 'route-admin', scope: 'workspace / all KBs', role: 'admin', answerModel: 'gpt-4.1-mini', embeddingModel: 'voyage-3-large', fallback: 'local-pilot', budget: '$120/day' },
  { id: 'route-editor', scope: 'kb: support-faq', role: 'editor', answerModel: 'gpt-4.1-mini', embeddingModel: 'text-embedding-3-small', fallback: 'disabled', budget: '$40/day' },
  { id: 'route-airgap', scope: 'kb: local-pilot', role: 'viewer', answerModel: 'llama3.1', embeddingModel: 'nomic-embed-text', fallback: 'none', budget: 'local only' },
]

export default function Models() {
  const [providers, setProviders] = useState(INITIAL_PROVIDERS)
  const [roleRoutes, setRoleRoutes] = useState(INITIAL_ROLE_ROUTES)
  const [editingRouteId, setEditingRouteId] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)
  const [message, setMessage] = useState('')
  const editingRoute = roleRoutes.find((route) => route.id === editingRouteId)

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

      <Panel
        title="Role model routing"
        description="Prototype for KB / role-specific model configuration before wiring the role-model-config API."
        actions={<Button variant="secondary" onClick={() => setMessage('New role route form opened for workspace / selected KB.')}>New route</Button>}
      >
        <DataTable
          rows={roleRoutes}
          getKey={(row) => row.id}
          columns={[
            { key: 'scope', label: 'Scope', render: (row) => <div><div className="font-medium text-ink">{row.scope}</div><div className="text-xs text-muted">{row.role}</div></div> },
            { key: 'answerModel', label: 'Answer model', render: (row) => <span className="font-mono text-xs">{row.answerModel}</span> },
            { key: 'embeddingModel', label: 'Embedding', render: (row) => <span className="font-mono text-xs">{row.embeddingModel}</span> },
            { key: 'fallback', label: 'Fallback', render: (row) => row.fallback },
            { key: 'budget', label: 'Budget', render: (row) => row.budget },
            { key: 'actions', label: 'Actions', align: 'right', render: (row) => <button onClick={() => setEditingRouteId(row.id)} className="rounded-lg border border-line px-2 py-1 text-xs font-medium text-brand hover:bg-blue-50">Edit</button> },
          ]}
        />
      </Panel>

      {showModal && (
        <SchemaModal
          title="New AI provider"
          schemas={PROVIDER_SCHEMAS}
          submitLabel="Create provider"
          onClose={() => setShowModal(false)}
          onSubmit={addProvider}
        />
      )}

      {editingRoute && (
        <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/30 px-4 py-6">
          <form
            className="w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-white shadow-xl"
            onSubmit={(event) => {
              event.preventDefault()
              setMessage(`${editingRoute.scope} model routing saved.`)
              setEditingRouteId(null)
            }}
          >
            <div className="border-b border-line bg-blue-50/70 px-5 py-4">
              <h2 className="text-base font-semibold text-ink">Edit model route</h2>
              <p className="mt-1 text-xs text-muted">{editingRoute.scope} · {editingRoute.role}</p>
            </div>
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              {(['answerModel', 'embeddingModel', 'fallback', 'budget'] as const).map((field) => (
                <label key={field} className="space-y-1">
                  <span className="text-xs font-medium text-slate-600">{field}</span>
                  <input
                    value={editingRoute[field]}
                    onChange={(event) => {
                      const value = event.target.value
                      setRoleRoutes((current) => current.map((route) => route.id === editingRoute.id ? { ...route, [field]: value } : route))
                    }}
                    className="w-full rounded-lg border border-line px-3 py-2 text-sm"
                  />
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2 border-t border-line bg-slate-50 px-5 py-4">
              <Button type="button" variant="secondary" onClick={() => setEditingRouteId(null)}>Cancel</Button>
              <Button type="submit">Save route</Button>
            </div>
          </form>
        </div>
      )}
    </ConsolePage>
  )
}
