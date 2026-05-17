import { useState } from 'react'
import { useSources, useKnowledgeBases, useCreateSource, useRunSourceIngest, useTask } from '../api/hooks'
import type { Source } from '../api/types'

// ── helpers ──────────────────────────────────────────────────────────────

function kindBadge(kind: string) {
  const map: Record<string, string> = {
    local_directory: 'bg-blue-100 text-blue-700',
    s3: 'bg-amber-100 text-amber-700',
    fileshare: 'bg-purple-100 text-purple-700',
    website: 'bg-teal-100 text-teal-700',
  }
  return map[kind] ?? 'bg-gray-100 text-gray-600'
}

function kindToPluginId(kind: string): string {
  const map: Record<string, string> = {
    fileshare: 'source.fileshare',
    s3: 'source.s3',
    local_directory: 'source.local',
    website: 'source.website',
  }
  return map[kind] ?? `source.${kind}`
}

function ConfigSummary({ config }: { config: Record<string, unknown> }) {
  const entries = Object.entries(config).filter(
    ([k]) => !['password', 'secret_key', 'access_key', 'private_key', 'api_key'].includes(k),
  )
  if (entries.length === 0) return <span className="text-gray-400">—</span>
  return (
    <div className="flex flex-wrap gap-1">
      {entries.slice(0, 4).map(([k, v]) => (
        <span key={k} className="text-[11px] bg-gray-100 rounded px-1 py-0.5 font-mono text-gray-600">
          {k}={String(v).slice(0, 24)}
        </span>
      ))}
      {entries.length > 4 && (
        <span className="text-[11px] text-gray-400">+{entries.length - 4} more</span>
      )}
    </div>
  )
}

// ── Run button with task status ───────────────────────────────────────────

function RunButton({ source }: { source: Source }) {
  const runIngest = useRunSourceIngest()
  const [taskId, setTaskId] = useState<string | null>(null)
  const { data: task } = useTask(taskId)

  const handleRun = async () => {
    try {
      const res = await runIngest.mutateAsync({
        plugin_id: kindToPluginId(source.kind),
        config: source.config as Record<string, unknown>,
        knowledge_base: source.knowledge_base ?? 'default',
      })
      setTaskId(res.task_id)
    } catch {
      // error shown inline
    }
  }

  const isRunning = runIngest.isPending || (task && task.status === 'running')
  const isDone = task?.status === 'completed'
  const isFailed = task?.status === 'failed'

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handleRun}
        disabled={!!isRunning}
        className="text-xs px-2 py-1 rounded bg-brand text-white hover:bg-brand/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {isRunning ? 'Running…' : 'Run'}
      </button>
      {isDone && <span className="text-[11px] text-emerald-600 font-bold">done</span>}
      {isFailed && <span className="text-[11px] text-red-500 font-bold">failed</span>}
      {runIngest.isError && (
        <span className="text-[11px] text-red-500 truncate max-w-[120px]" title={runIngest.error?.message}>
          {runIngest.error?.message}
        </span>
      )}
    </div>
  )
}

// ── Source type definitions ───────────────────────────────────────────────

type SourceType = 'fileshare' | 's3' | 'local'

interface SourceTypeOption {
  id: SourceType
  pluginId: string
  label: string
  description: string
  badge: string
}

const SOURCE_TYPES: SourceTypeOption[] = [
  {
    id: 'fileshare',
    pluginId: 'source.fileshare',
    label: 'Fileshare / SMB',
    description: 'SMB, WebDAV, or SFTP — enterprise file shares and network drives',
    badge: 'bg-purple-100 text-purple-700',
  },
  {
    id: 's3',
    pluginId: 'source.s3',
    label: 'S3 / MinIO',
    description: 'S3-compatible object storage — AWS S3, MinIO, Cloudflare R2, etc.',
    badge: 'bg-amber-100 text-amber-700',
  },
  {
    id: 'local',
    pluginId: 'source.local',
    label: 'Local Directory',
    description: 'Files from a directory path inside the container',
    badge: 'bg-blue-100 text-blue-700',
  },
]

// ── Config field components ───────────────────────────────────────────────

function TextField({
  label, value, onChange, placeholder, hint, required,
}: {
  label: string; value: string
  onChange: (v: string) => void; placeholder?: string; hint?: string; required?: boolean
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-gray-600">
        {label}{required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40"
      />
      {hint && <p className="text-[11px] text-gray-400">{hint}</p>}
    </div>
  )
}

function SelectField({
  label, value, onChange, options,
}: {
  label: string; value: string
  onChange: (v: string) => void; options: { value: string; label: string }[]
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-gray-600">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
      >
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

function CheckField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="rounded border-gray-300 text-brand focus:ring-brand/40"
      />
      <span className="text-xs text-gray-700">{label}</span>
    </label>
  )
}

// ── Add Source Modal ──────────────────────────────────────────────────────

function AddSourceModal({
  kbs,
  onClose,
}: {
  kbs: { id: string; name: string }[]
  onClose: () => void
}) {
  const createSource = useCreateSource()
  const runIngest = useRunSourceIngest()
  const [taskId, setTaskId] = useState<string | null>(null)
  const { data: task } = useTask(taskId)

  const [step, setStep] = useState<'type' | 'config'>('type')
  const [sourceType, setSourceType] = useState<SourceTypeOption | null>(null)
  const [kbName, setKbName] = useState(kbs[0]?.name ?? 'default')
  const [runNow, setRunNow] = useState(true)

  // Fileshare fields
  const [fsProtocol, setFsProtocol] = useState('smb')
  const [fsHost, setFsHost] = useState('')
  const [fsShare, setFsShare] = useState('')
  const [fsRootPath, setFsRootPath] = useState('/')
  const [fsUsername, setFsUsername] = useState('env:FILESHARE_USERNAME')
  const [fsPassword, setFsPassword] = useState('env:FILESHARE_PASSWORD')

  // S3 fields
  const [s3Endpoint, setS3Endpoint] = useState('')
  const [s3Bucket, setS3Bucket] = useState('')
  const [s3Prefix, setS3Prefix] = useState('')
  const [s3Region, setS3Region] = useState('us-east-1')
  const [s3PathStyle, setS3PathStyle] = useState(true)
  const [s3AccessKey, setS3AccessKey] = useState('env:AWS_ACCESS_KEY_ID')
  const [s3SecretKey, setS3SecretKey] = useState('env:AWS_SECRET_ACCESS_KEY')

  // Local fields
  const [localPath, setLocalPath] = useState('')

  const buildConfig = (): Record<string, unknown> => {
    if (!sourceType) return {}
    if (sourceType.id === 'fileshare') {
      const cfg: Record<string, unknown> = {
        protocol: fsProtocol,
        host: fsHost,
        root_path: fsRootPath,
        username: fsUsername,
        password: fsPassword,
      }
      if (fsProtocol === 'smb') cfg.share = fsShare
      return cfg
    }
    if (sourceType.id === 's3') {
      return {
        bucket: s3Bucket,
        prefix: s3Prefix || undefined,
        endpoint_url: s3Endpoint || undefined,
        region: s3Region,
        use_path_style: s3PathStyle,
        access_key: s3AccessKey,
        secret_key: s3SecretKey,
      }
    }
    if (sourceType.id === 'local') {
      return { path: localPath }
    }
    return {}
  }

  const isConfigValid = (): boolean => {
    if (!sourceType) return false
    if (!kbName) return false
    if (sourceType.id === 'fileshare') return !!fsHost
    if (sourceType.id === 's3') return !!s3Bucket
    if (sourceType.id === 'local') return !!localPath
    return false
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!sourceType || !isConfigValid()) return
    const config = buildConfig()
    try {
      await createSource.mutateAsync({ plugin_id: sourceType.pluginId, config, knowledge_base: kbName })
      if (runNow) {
        const res = await runIngest.mutateAsync({ plugin_id: sourceType.pluginId, config, knowledge_base: kbName })
        setTaskId(res.task_id)
      } else {
        onClose()
      }
    } catch {
      // errors shown inline
    }
  }

  const isWorking = createSource.isPending || runIngest.isPending
  const isTaskDone = task?.status === 'completed' || task?.status === 'failed'

  if (taskId && task) {
    return (
      <ModalShell onClose={onClose} title="Ingestion started">
        <div className="space-y-4 p-6">
          <div className="flex items-center gap-3">
            {!isTaskDone && (
              <svg className="animate-spin h-5 w-5 text-brand" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
            )}
            <div>
              <div className="text-sm font-medium text-gray-800">
                {task.status === 'completed' ? 'Ingestion completed' : task.status === 'failed' ? 'Ingestion failed' : 'Running ingestion…'}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">Task: {taskId.slice(0, 8)}…</div>
            </div>
          </div>
          {task.error && (
            <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{task.error}</div>
          )}
          <button onClick={onClose} className="text-sm text-brand hover:underline">
            {isTaskDone ? 'Close' : 'Close (continues in background)'}
          </button>
        </div>
      </ModalShell>
    )
  }

  return (
    <ModalShell onClose={onClose} title="Add source">
      {step === 'type' ? (
        <div className="p-6 space-y-4">
          <p className="text-sm text-gray-500">Choose the source type to connect to this knowledge base.</p>
          <div className="space-y-2">
            {SOURCE_TYPES.map((t) => (
              <button
                key={t.id}
                onClick={() => { setSourceType(t); setStep('config') }}
                className="w-full text-left border border-gray-200 rounded-lg p-4 hover:border-brand/40 hover:bg-brand/5 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${t.badge}`}>{t.label}</span>
                  <span className="text-sm text-gray-700">{t.description}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          <button
            type="button"
            onClick={() => setStep('type')}
            className="text-xs text-brand hover:underline"
          >
            ← Change type
          </button>

          <div className="flex items-center gap-2">
            <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${sourceType!.badge}`}>
              {sourceType!.label}
            </span>
          </div>

          {/* KB picker */}
          <SelectField
            label="Knowledge base"
           
            value={kbName}
            onChange={setKbName}
            options={kbs.map((k) => ({ value: k.name, label: k.name }))}
          />

          {/* Fileshare fields */}
          {sourceType?.id === 'fileshare' && (
            <>
              <SelectField
                label="Protocol"
               
                value={fsProtocol}
                onChange={setFsProtocol}
                options={[
                  { value: 'smb', label: 'SMB (Windows file share)' },
                  { value: 'webdav', label: 'WebDAV (NextCloud, OwnCloud, etc.)' },
                  { value: 'sftp', label: 'SFTP' },
                ]}
              />
              <TextField label="Host" value={fsHost} onChange={setFsHost}
                placeholder="files.example.internal" required />
              {fsProtocol === 'smb' && (
                <TextField label="Share name" value={fsShare} onChange={setFsShare}
                  placeholder="documents" />
              )}
              <TextField label="Root path" value={fsRootPath} onChange={setFsRootPath}
                placeholder="/" />
              <TextField label="Username" value={fsUsername} onChange={setFsUsername}
                hint="Use env:VAR_NAME to reference an environment variable set on the server." />
              <TextField label="Password" value={fsPassword} onChange={setFsPassword}
                hint="Use env:VAR_NAME to avoid storing secrets in the UI." />
            </>
          )}

          {/* S3 fields */}
          {sourceType?.id === 's3' && (
            <>
              <TextField label="Endpoint URL" value={s3Endpoint} onChange={setS3Endpoint}
                placeholder="http://minio:9000 (leave blank for AWS)"
                hint="Leave blank for AWS S3. Set for MinIO or S3-compatible services." />
              <TextField label="Bucket" value={s3Bucket} onChange={setS3Bucket}
                placeholder="my-docs-bucket" required />
              <TextField label="Prefix (optional)" value={s3Prefix} onChange={setS3Prefix}
                placeholder="team-a/knowledge" />
              <TextField label="Region" value={s3Region} onChange={setS3Region}
                placeholder="us-east-1" />
              <CheckField label="Use path-style addressing (required for MinIO)" checked={s3PathStyle} onChange={setS3PathStyle} />
              <TextField label="Access key" value={s3AccessKey} onChange={setS3AccessKey}
                hint="Use env:AWS_ACCESS_KEY_ID to reference a server-side env var." />
              <TextField label="Secret key" value={s3SecretKey} onChange={setS3SecretKey}
                hint="Use env:AWS_SECRET_ACCESS_KEY to avoid storing secrets in the UI." />
            </>
          )}

          {/* Local directory fields */}
          {sourceType?.id === 'local' && (
            <TextField label="Directory path" value={localPath} onChange={setLocalPath}
              placeholder="/data/docs"
              hint="Absolute path inside the container. Mount the directory via docker-compose volumes."
              required />
          )}

          <CheckField label="Run ingestion immediately after saving" checked={runNow} onChange={setRunNow} />

          {(createSource.isError || runIngest.isError) && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
              {createSource.error?.message ?? runIngest.error?.message}
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button
              type="submit"
              disabled={isWorking || !isConfigValid()}
              className="px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {isWorking ? 'Saving…' : runNow ? 'Save & run' : 'Save'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </ModalShell>
  )
}

function ModalShell({ onClose, title, children }: { onClose: () => void; title: string; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/20" />
      <div
        className="relative h-full w-full max-w-md bg-white shadow-xl flex flex-col overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-sm font-bold text-gray-900">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
        </div>
        {children}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function Sources() {
  const { data: sources, isLoading } = useSources()
  const { data: kbs } = useKnowledgeBases()
  const [showAdd, setShowAdd] = useState(false)

  const byKB = (sources ?? []).reduce<Record<string, Source[]>>((acc, s) => {
    const kb = s.knowledge_base ?? '(none)'
    acc[kb] = [...(acc[kb] ?? []), s]
    return acc
  }, {})

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Sources</h1>
          <p className="text-gray-500 text-sm mt-0.5">Data source connectors attached to knowledge bases</p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="px-3 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 transition-colors"
        >
          + Add source
        </button>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : !sources?.length ? (
        <div className="bg-white border border-gray-200 rounded-lg p-8 text-center">
          <p className="text-gray-500 text-sm font-medium">No sources configured yet</p>
          <p className="text-gray-400 text-xs mt-1">
            Add a fileshare, S3 bucket, or local directory to start ingesting documents automatically.
          </p>
          <button
            onClick={() => setShowAdd(true)}
            className="mt-4 px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 transition-colors"
          >
            Add first source
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(byKB).sort().map(([kb, items]) => (
            <div key={kb}>
              <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-2">{kb}</h2>
              <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Kind</th>
                      <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">URI</th>
                      <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Config</th>
                      <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Added</th>
                      <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((s, i) => (
                      <tr key={s.id} className={`border-b border-gray-100 ${i % 2 === 0 ? '' : 'bg-gray-50'}`}>
                        <td className="px-4 py-2.5">
                          <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${kindBadge(s.kind)}`}>
                            {s.kind}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 font-mono text-xs text-gray-700 max-w-xs truncate">
                          {s.uri}
                        </td>
                        <td className="px-4 py-2.5">
                          <ConfigSummary config={s.config} />
                        </td>
                        <td className="px-4 py-2.5 text-gray-400 text-xs whitespace-nowrap">
                          {new Date(s.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-2.5">
                          <RunButton source={s} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <AddSourceModal
          kbs={kbs ?? []}
          onClose={() => setShowAdd(false)}
        />
      )}
    </div>
  )
}
