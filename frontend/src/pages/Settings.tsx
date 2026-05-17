import { useState } from 'react'
import { useSystemStatus, useApiKeys, useCreateApiKey, useRevokeApiKey } from '../api/hooks'
import type { ApiKeyRecord, CreatedApiKey } from '../api/hooks'
import StatusCard from '../components/StatusCard'

function statusOf(s: string): 'ok' | 'warn' | 'error' | 'neutral' {
  if (s === 'ok' || s === 'connected' || s === 'ready') return 'ok'
  if (s === 'degraded') return 'warn'
  if (s === 'error' || s === 'unavailable') return 'error'
  return 'neutral'
}

const CONFIG_DOCS: { label: string; env: string; description: string }[] = [
  { label: 'Database URL', env: 'DATABASE_URL', description: 'PostgreSQL connection string (postgres://user:pass@host/db)' },
  { label: 'Vector backend', env: 'RAGRIG_VECTOR_BACKEND', description: 'Vector store type: pgvector (default), qdrant' },
  { label: 'Qdrant URL', env: 'QDRANT_URL', description: 'Required when RAGRIG_VECTOR_BACKEND=qdrant' },
  { label: 'Task executor', env: 'RAGRIG_TASK_EXECUTOR', description: 'Task executor type: thread_pool (default), synchronous' },
  { label: 'Default workspace', env: 'RAGRIG_DEFAULT_WORKSPACE_ID', description: 'UUID of the default workspace' },
]

// ── Create key modal ─────────────────────────────────────────────────────────

function CreateKeyModal({ onClose, onCreated }: { onClose: () => void; onCreated: (k: CreatedApiKey) => void }) {
  const create = useCreateApiKey()
  const [name, setName] = useState('')
  const [expiresDays, setExpiresDays] = useState('90')

  async function handleCreate() {
    const days = parseInt(expiresDays, 10)
    const result = await create.mutateAsync({
      name,
      scopes: [],
      expires_days: isNaN(days) || expiresDays === '' ? undefined : days,
    })
    onCreated(result)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-gray-900">Create API key</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Name</label>
          <input
            autoFocus
            className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40"
            placeholder="e.g. CI runner, my-app"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">
            Expires in (days) <span className="text-gray-400">— leave blank for no expiry</span>
          </label>
          <input
            type="number"
            min={1}
            max={3650}
            className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40"
            placeholder="90"
            value={expiresDays}
            onChange={(e) => setExpiresDays(e.target.value)}
          />
        </div>

        {create.isError && (
          <div className="text-xs text-red-600">{create.error?.message}</div>
        )}

        <div className="flex gap-2 pt-1">
          <button
            onClick={handleCreate}
            disabled={!name.trim() || create.isPending}
            className="flex-1 px-3 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {create.isPending ? 'Creating…' : 'Create key'}
          </button>
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Token reveal modal ───────────────────────────────────────────────────────

function TokenRevealModal({ created, onClose }: { created: CreatedApiKey; onClose: () => void }) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    navigator.clipboard.writeText(created.token)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-gray-900">API key created — copy it now</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-700">
          This is the only time the full key will be shown. Store it securely — it cannot be recovered.
        </div>

        <div className="flex items-center gap-2">
          <code className="flex-1 bg-gray-100 rounded-lg px-3 py-2 text-xs font-mono text-gray-800 break-all select-all">
            {created.token}
          </code>
          <button
            onClick={handleCopy}
            className="shrink-0 px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            {copied ? '✓' : 'Copy'}
          </button>
        </div>

        <div className="text-xs text-gray-500">
          <span className="font-medium">{created.name}</span>
          {created.expires_at && (
            <> · expires {new Date(created.expires_at).toLocaleDateString()}</>
          )}
        </div>

        <button
          onClick={onClose}
          className="w-full px-3 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 transition-colors"
        >
          Done
        </button>
      </div>
    </div>
  )
}

// ── Key row ──────────────────────────────────────────────────────────────────

function KeyRow({ apiKey }: { apiKey: ApiKeyRecord }) {
  const revoke = useRevokeApiKey()
  const [confirm, setConfirm] = useState(false)

  const isExpired = apiKey.expires_at ? new Date(apiKey.expires_at) < new Date() : false

  return (
    <div className="flex items-start gap-3 px-4 py-3 border-b border-gray-100 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-gray-800">{apiKey.name}</span>
          <span className="text-xs font-mono text-gray-400">{apiKey.prefix}…</span>
          {isExpired && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-50 text-amber-700">expired</span>
          )}
        </div>
        <div className="flex gap-3 mt-0.5 text-xs text-gray-400 flex-wrap">
          <span>Created {new Date(apiKey.created_at).toLocaleDateString()}</span>
          {apiKey.last_used_at && (
            <span>Last used {new Date(apiKey.last_used_at).toLocaleDateString()}</span>
          )}
          {apiKey.expires_at && !isExpired && (
            <span>Expires {new Date(apiKey.expires_at).toLocaleDateString()}</span>
          )}
          {apiKey.scopes.length > 0 && (
            <span>Scopes: {apiKey.scopes.join(', ')}</span>
          )}
        </div>
      </div>
      {!confirm ? (
        <button
          onClick={() => setConfirm(true)}
          className="shrink-0 text-xs px-2 py-1 rounded border border-red-200 text-red-500 hover:bg-red-50 transition-colors"
        >
          Revoke
        </button>
      ) : (
        <button
          onClick={() => revoke.mutate(apiKey.id)}
          disabled={revoke.isPending}
          className="shrink-0 text-xs px-2 py-1 rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-40 transition-colors"
        >
          {revoke.isPending ? 'Revoking…' : 'Confirm'}
        </button>
      )}
    </div>
  )
}

// ── API Keys section ─────────────────────────────────────────────────────────

function ApiKeysSection() {
  const { data: keys, isLoading } = useApiKeys()
  const [showCreate, setShowCreate] = useState(false)
  const [created, setCreated] = useState<CreatedApiKey | null>(null)

  function handleCreated(k: CreatedApiKey) {
    setShowCreate(false)
    setCreated(k)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-700">API keys</h2>
        <button
          onClick={() => setShowCreate(true)}
          className="px-3 py-1 text-xs font-medium bg-brand text-white rounded-lg hover:bg-brand/90 transition-colors"
        >
          + Create key
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-4 text-sm text-gray-400">Loading…</div>
        ) : !keys?.length ? (
          <div className="p-4 text-sm text-gray-400">
            No API keys. Create one to authenticate programmatic access.
          </div>
        ) : (
          keys.map((k) => <KeyRow key={k.id} apiKey={k} />)
        )}
      </div>

      <p className="text-[11px] text-gray-400 mt-2">
        Keys are workspace-scoped. Pass as{' '}
        <code className="font-mono bg-gray-100 px-1 rounded">Authorization: Bearer &lt;token&gt;</code>.
      </p>

      {showCreate && <CreateKeyModal onClose={() => setShowCreate(false)} onCreated={handleCreated} />}
      {created && <TokenRevealModal created={created} onClose={() => setCreated(null)} />}
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function Settings() {
  const { data: status } = useSystemStatus()

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 text-sm mt-0.5">System settings and configuration</p>
      </div>

      {status && (
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">System status</h2>
          <div className="flex gap-3 flex-wrap">
            <StatusCard label="API" value={status.api} status={statusOf(status.api)} sub={status.api_version} />
            <StatusCard label="Database" value={status.database} status={statusOf(status.database)}
              sub={status.database_detail ?? undefined} />
            <StatusCard label="Vector" value={status.vector} status={statusOf(status.vector)}
              sub={status.vector_detail ?? undefined} />
            <StatusCard label="KBs" value={status.knowledge_bases} />
            <StatusCard label="Profiles" value={status.embedding_profiles} />
          </div>
        </div>
      )}

      <ApiKeysSection />

      <div>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Environment variables</h2>
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          {CONFIG_DOCS.map((c) => (
            <div key={c.env} className="px-4 py-3 border-b border-gray-100 last:border-0">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono font-bold text-gray-800 bg-gray-100 px-1.5 py-0.5 rounded">
                      {c.env}
                    </span>
                    <span className="text-xs text-gray-500">{c.label}</span>
                  </div>
                  <div className="text-xs text-gray-400 mt-0.5">{c.description}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Resources</h2>
        <div className="grid grid-cols-2 gap-3">
          {[
            { label: 'API documentation', href: '/docs', desc: 'OpenAPI / Swagger UI' },
            { label: 'Legacy console', href: '/console', desc: 'HTML web console' },
          ].map((link) => (
            <a
              key={link.href}
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="bg-white border border-gray-200 rounded-lg px-4 py-3 hover:bg-gray-50 transition-colors"
            >
              <div className="text-sm font-medium text-brand">{link.label} ↗</div>
              <div className="text-xs text-gray-400 mt-0.5">{link.desc}</div>
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}
