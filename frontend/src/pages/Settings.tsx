import { useSystemStatus } from '../api/hooks'
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

export default function Settings() {
  const { data: status } = useSystemStatus()

  return (
    <div className="p-6 space-y-6 max-w-2xl">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 text-sm mt-0.5">System settings and configuration</p>
      </div>

      {/* Live status */}
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

      {/* Config reference */}
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

      {/* Links */}
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
