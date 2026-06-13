import { useMemo, useState } from 'react'
import {
  useKnowledgeBases,
  useSaveStageModelPolicy,
  useStageModelPolicy,
} from '../api/hooks'
import type { StageModelConfig } from '../api/types'
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

const STAGES = ['parse', 'understand', 'extract', 'query', 'rerank', 'answer', 'judge'] as const

function editablePolicy(policy: Record<string, StageModelConfig>) {
  return Object.fromEntries(
    Object.entries(policy).map(([stage, entry]) => [
      stage,
      Object.fromEntries(
        Object.entries(entry).filter(([key]) => !['has_config', 'config_keys'].includes(key)),
      ),
    ]),
  )
}

export default function Models() {
  const { data: knowledgeBases } = useKnowledgeBases()
  const [providers, setProviders] = useState(INITIAL_PROVIDERS)
  const [roleRoutes, setRoleRoutes] = useState(INITIAL_ROLE_ROUTES)
  const [editingRouteId, setEditingRouteId] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)
  const [message, setMessage] = useState('')
  const [selectedKbId, setSelectedKbId] = useState('')
  const [policyDrafts, setPolicyDrafts] = useState<Record<string, string>>({})
  const editingRoute = roleRoutes.find((route) => route.id === editingRouteId)
  const activeKbId = selectedKbId || knowledgeBases?.[0]?.id || ''
  const policyQuery = useStageModelPolicy(activeKbId || null)
  const savePolicy = useSaveStageModelPolicy()
  const stageRows = useMemo(
    () => {
      const policy = policyQuery.data?.policy ?? {}
      return STAGES.map((stage) => ({
        id: stage,
        stage,
        provider: policy[stage]?.provider ?? '--',
        model: policy[stage]?.model ?? '--',
        source: policy[stage] ? 'stage_model_policy' : 'default',
        enabled: policy[stage]?.enabled === false ? 'disabled' : 'enabled',
        budget: policy[stage]?.budget_hint_usd,
        configKeys: policy[stage]?.config_keys ?? [],
      }))
    },
    [policyQuery.data?.policy],
  )
  const loadedPolicyEditor = useMemo(
    () => JSON.stringify(editablePolicy(policyQuery.data?.policy ?? {}), null, 2),
    [policyQuery.data?.policy],
  )
  const policyEditor = policyDrafts[activeKbId] ?? loadedPolicyEditor

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

  async function saveStagePolicy() {
    if (!activeKbId) return
    try {
      const parsed = JSON.parse(policyEditor)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('Policy must be a JSON object keyed by stage.')
      }
      await savePolicy.mutateAsync({ kbId: activeKbId, policy: parsed })
      setPolicyDrafts((current) => {
        const next = { ...current }
        delete next[activeKbId]
        return next
      })
      setMessage('Stage model policy saved. Existing secret config is preserved when omitted.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Failed to save stage model policy.')
    }
  }

  return (
    <ConsolePage
      title="AI Providers"
      description="Model providers, embedding profiles, fallbacks, and health state."
      actions={<Button onClick={() => setShowModal(true)}>New provider</Button>}
    >
      <Panel
        title="Stage model policy"
        description="Live KB policy for parse, understand, extract, query, rerank, answer, and judge. Secret config values are never returned."
        actions={
          <Button
            variant="secondary"
            onClick={saveStagePolicy}
            disabled={!activeKbId || savePolicy.isPending}
          >
            {savePolicy.isPending ? 'Saving...' : 'Save stage policy'}
          </Button>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[1fr_420px]">
          <div className="space-y-3">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-slate-600">Knowledge base</span>
              <select
                aria-label="Stage policy knowledge base"
                value={activeKbId}
                onChange={(event) => setSelectedKbId(event.target.value)}
                className="w-full rounded-lg border border-line px-3 py-2 text-sm"
              >
                {(knowledgeBases ?? []).map((kb) => (
                  <option key={kb.id} value={kb.id}>
                    {kb.name}
                  </option>
                ))}
              </select>
            </label>
            <DataTable
              rows={stageRows}
              getKey={(row) => row.id}
              columns={[
                { key: 'stage', label: 'Stage', render: (row) => <span className="font-mono text-xs">{row.stage}</span> },
                { key: 'provider', label: 'Provider / model', render: (row) => <div><div>{row.provider}</div><div className="font-mono text-xs text-muted">{row.model}</div></div> },
                { key: 'source', label: 'Source', render: (row) => <StatusPill tone={row.source === 'default' ? 'neutral' : 'ok'}>{row.source}</StatusPill> },
                { key: 'enabled', label: 'Enabled', render: (row) => row.enabled },
                { key: 'budget', label: 'Cost hint', render: (row) => typeof row.budget === 'number' ? `$${row.budget.toFixed(4)}` : '--' },
                { key: 'configKeys', label: 'Config keys', render: (row) => row.configKeys.join(', ') || '--' },
              ]}
            />
          </div>
          <label className="space-y-1">
            <span className="text-xs font-medium text-slate-600">Policy JSON</span>
            <textarea
              aria-label="Stage model policy JSON"
              value={policyEditor}
              onChange={(event) =>
                setPolicyDrafts((current) => ({ ...current, [activeKbId]: event.target.value }))
              }
              rows={22}
              className="w-full rounded-lg border border-line bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100"
            />
            <span className="block text-xs text-muted">
              Priority: request override, role model config, stage model policy, endpoint default.
              Omitted config preserves existing secret-backed config.
            </span>
          </label>
        </div>
      </Panel>

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
