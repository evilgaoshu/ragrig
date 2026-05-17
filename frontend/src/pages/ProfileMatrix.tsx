import { useState } from 'react'
import {
  useProcessingProfileMatrix,
  useCreateProcessingProfile,
  usePatchProcessingProfile,
  useDeleteProcessingProfile,
} from '../api/hooks'

type Cell = {
  profile_id: string
  extension: string
  task_type: string
  display_name: string
  provider: string
  model_id?: string | null
  status: string
  kind: string
  source: string
  is_default: boolean
  provider_available: boolean
}

type MatrixData = {
  extensions: string[]
  task_types: string[]
  cells: Record<string, Cell>
}

const TASK_TYPES = ['correct', 'clean', 'chunk', 'summarize', 'understand', 'embed', 'answer']
const STATUSES = ['active', 'deprecated', 'experimental', 'disabled']
const KINDS = ['deterministic', 'LLM-assisted']

function kindColor(kind: string) {
  if (kind === 'deterministic') return 'text-blue-700 bg-blue-50'
  if (kind === 'LLM-assisted' || kind === 'llm-assisted') return 'text-violet-700 bg-violet-50'
  return 'text-gray-600 bg-gray-100'
}

function statusColor(status: string) {
  switch (status) {
    case 'active': return 'text-emerald-700 bg-emerald-50'
    case 'deprecated': return 'text-amber-700 bg-amber-50'
    case 'experimental': return 'text-blue-700 bg-blue-50'
    case 'disabled': return 'text-gray-500 bg-gray-100'
    default: return 'text-gray-600 bg-gray-100'
  }
}

// ── Shared form field ────────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      {children}
    </div>
  )
}

const inputCls = 'w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40'

// ── Edit panel (for existing overrides) ─────────────────────────────────────

function EditPanel({ cell, onClose }: { cell: Cell; onClose: () => void }) {
  const patch = usePatchProcessingProfile()
  const del = useDeleteProcessingProfile()
  const [confirmDelete, setConfirmDelete] = useState(false)

  const [form, setForm] = useState({
    display_name: cell.display_name,
    provider: cell.provider,
    model_id: cell.model_id ?? '',
    kind: cell.kind === 'LLM-assisted' || cell.kind === 'llm-assisted' ? 'LLM-assisted' : 'deterministic',
    status: cell.status,
  })

  function set(k: keyof typeof form, v: string) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  async function handleSave() {
    await patch.mutateAsync({
      profileId: cell.profile_id,
      display_name: form.display_name || undefined,
      provider: form.provider || undefined,
      model_id: form.model_id || null,
      kind: form.kind,
      status: form.status,
    })
    onClose()
  }

  async function handleDelete() {
    await del.mutateAsync(cell.profile_id)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/20" onClick={onClose} />
      <aside className="w-96 bg-white shadow-xl flex flex-col overflow-y-auto">
        <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Edit override</h2>
            <div className="text-xs text-gray-400 font-mono mt-0.5">{cell.profile_id}</div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <div className="flex-1 px-5 py-4 space-y-4">
          <div className="text-xs text-gray-500 bg-gray-50 rounded-lg px-3 py-2 font-mono">
            {cell.extension} · {cell.task_type}
          </div>

          <Field label="Display name">
            <input className={inputCls} value={form.display_name}
              onChange={(e) => set('display_name', e.target.value)} />
          </Field>

          <Field label="Provider">
            <input className={inputCls} value={form.provider}
              onChange={(e) => set('provider', e.target.value)}
              placeholder="e.g. openai, local, custom-plugin" />
          </Field>

          <Field label="Model ID (optional)">
            <input className={inputCls} value={form.model_id}
              onChange={(e) => set('model_id', e.target.value)}
              placeholder="e.g. gpt-4o-mini" />
          </Field>

          <Field label="Kind">
            <select className={inputCls} value={form.kind} onChange={(e) => set('kind', e.target.value)}>
              {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </Field>

          <Field label="Status">
            <select className={inputCls} value={form.status} onChange={(e) => set('status', e.target.value)}>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>

          {patch.isError && (
            <div className="text-xs text-red-600">{patch.error?.message}</div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-gray-200 flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={patch.isPending}
            className="flex-1 px-3 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 disabled:opacity-40 transition-colors"
          >
            {patch.isPending ? 'Saving…' : 'Save'}
          </button>
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
            Cancel
          </button>
          {!confirmDelete ? (
            <button onClick={() => setConfirmDelete(true)} className="px-3 py-1.5 text-sm text-red-500 border border-red-200 rounded-lg hover:bg-red-50 transition-colors">
              Delete
            </button>
          ) : (
            <button
              onClick={handleDelete}
              disabled={del.isPending}
              className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-40 transition-colors"
            >
              {del.isPending ? 'Deleting…' : 'Confirm'}
            </button>
          )}
        </div>
      </aside>
    </div>
  )
}

// ── Create override panel ────────────────────────────────────────────────────

function CreatePanel({ ext, tt, onClose }: { ext: string; tt: string; onClose: () => void }) {
  const create = useCreateProcessingProfile()
  const [form, setForm] = useState({
    profile_id: `${ext}.${tt}.override`.replace(/[^a-z0-9._-]/g, '-'),
    display_name: '',
    provider: '',
    model_id: '',
    kind: 'deterministic' as string,
  })

  function set(k: keyof typeof form, v: string) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  async function handleCreate() {
    await create.mutateAsync({
      profile_id: form.profile_id,
      extension: ext,
      task_type: tt,
      display_name: form.display_name,
      description: `Override for ${ext}/${tt}`,
      provider: form.provider,
      model_id: form.model_id || undefined,
      kind: form.kind,
    })
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/20" onClick={onClose} />
      <aside className="w-96 bg-white shadow-xl flex flex-col overflow-y-auto">
        <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Create override</h2>
            <div className="text-xs text-gray-400 font-mono mt-0.5">{ext} · {tt}</div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <div className="flex-1 px-5 py-4 space-y-4">
          <Field label="Profile ID">
            <input className={inputCls} value={form.profile_id}
              onChange={(e) => set('profile_id', e.target.value)} />
          </Field>

          <Field label="Display name">
            <input className={inputCls} value={form.display_name}
              onChange={(e) => set('display_name', e.target.value)}
              placeholder="My custom profile" />
          </Field>

          <Field label="Provider">
            <input className={inputCls} value={form.provider}
              onChange={(e) => set('provider', e.target.value)}
              placeholder="e.g. openai, local, custom-plugin" />
          </Field>

          <Field label="Model ID (optional)">
            <input className={inputCls} value={form.model_id}
              onChange={(e) => set('model_id', e.target.value)}
              placeholder="e.g. gpt-4o-mini" />
          </Field>

          <Field label="Kind">
            <select className={inputCls} value={form.kind} onChange={(e) => set('kind', e.target.value)}>
              {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </Field>

          {create.isError && (
            <div className="text-xs text-red-600">{create.error?.message}</div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-gray-200 flex gap-2">
          <button
            onClick={handleCreate}
            disabled={create.isPending || !form.display_name || !form.provider}
            className="flex-1 px-3 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {create.isPending ? 'Creating…' : 'Create override'}
          </button>
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
            Cancel
          </button>
        </div>
      </aside>
    </div>
  )
}

// ── Add override panel (pick ext+tt freely) ──────────────────────────────────

function AddPanel({ extensions, onClose }: { extensions: string[]; onClose: () => void }) {
  const create = useCreateProcessingProfile()
  const [form, setForm] = useState({
    extension: extensions[0] ?? '',
    task_type: TASK_TYPES[0],
    profile_id: '',
    display_name: '',
    provider: '',
    model_id: '',
    kind: 'deterministic' as string,
  })

  function set(k: keyof typeof form, v: string) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  async function handleCreate() {
    await create.mutateAsync({
      profile_id: form.profile_id || `${form.extension}.${form.task_type}.override`.replace(/[^a-z0-9._-]/g, '-'),
      extension: form.extension,
      task_type: form.task_type,
      display_name: form.display_name,
      description: `Override for ${form.extension}/${form.task_type}`,
      provider: form.provider,
      model_id: form.model_id || undefined,
      kind: form.kind,
    })
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/20" onClick={onClose} />
      <aside className="w-96 bg-white shadow-xl flex flex-col overflow-y-auto">
        <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-sm font-bold text-gray-900">Add override</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <div className="flex-1 px-5 py-4 space-y-4">
          <Field label="Extension">
            <input className={inputCls} value={form.extension}
              onChange={(e) => set('extension', e.target.value)}
              placeholder=".pdf" list="ext-list" />
            <datalist id="ext-list">
              {extensions.map((e) => <option key={e} value={e} />)}
            </datalist>
          </Field>

          <Field label="Task type">
            <select className={inputCls} value={form.task_type} onChange={(e) => set('task_type', e.target.value)}>
              {TASK_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>

          <Field label="Profile ID (auto-generated if blank)">
            <input className={inputCls} value={form.profile_id}
              onChange={(e) => set('profile_id', e.target.value)}
              placeholder="my-pdf-chunk-override" />
          </Field>

          <Field label="Display name">
            <input className={inputCls} value={form.display_name}
              onChange={(e) => set('display_name', e.target.value)}
              placeholder="My custom profile" />
          </Field>

          <Field label="Provider">
            <input className={inputCls} value={form.provider}
              onChange={(e) => set('provider', e.target.value)}
              placeholder="e.g. openai, local" />
          </Field>

          <Field label="Model ID (optional)">
            <input className={inputCls} value={form.model_id}
              onChange={(e) => set('model_id', e.target.value)}
              placeholder="e.g. gpt-4o-mini" />
          </Field>

          <Field label="Kind">
            <select className={inputCls} value={form.kind} onChange={(e) => set('kind', e.target.value)}>
              {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </Field>

          {create.isError && (
            <div className="text-xs text-red-600">{create.error?.message}</div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-gray-200 flex gap-2">
          <button
            onClick={handleCreate}
            disabled={create.isPending || !form.display_name || !form.provider || !form.extension}
            className="flex-1 px-3 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {create.isPending ? 'Creating…' : 'Create override'}
          </button>
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
            Cancel
          </button>
        </div>
      </aside>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

type Panel =
  | { type: 'edit'; cell: Cell }
  | { type: 'create'; ext: string; tt: string }
  | { type: 'add' }
  | null

export default function ProfileMatrix() {
  const { data, isLoading } = useProcessingProfileMatrix()
  const [selectedExt, setSelectedExt] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [panel, setPanel] = useState<Panel>(null)

  const matrix = data as MatrixData | undefined

  if (isLoading) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-bold text-gray-900 mb-4">Profile Matrix</h1>
        <div className="text-gray-400 text-sm">Loading…</div>
      </div>
    )
  }

  if (!matrix) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-bold text-gray-900 mb-4">Profile Matrix</h1>
        <div className="text-sm text-gray-400">No matrix data available.</div>
      </div>
    )
  }

  const extensions = matrix.extensions ?? []
  const taskTypes = matrix.task_types ?? []
  const cells = matrix.cells ?? {}

  const filteredExts = extensions.filter((ext) => {
    if (selectedExt && ext !== selectedExt) return false
    if (search) return ext.toLowerCase().includes(search.toLowerCase())
    return true
  })

  const overrideCount = Object.values(cells).filter((c) => !c.is_default).length
  const unavailableCount = Object.values(cells).filter((c) => !c.provider_available).length

  function openCell(ext: string, tt: string) {
    const cell = cells[`${ext}.${tt}`]
    if (!cell) {
      setPanel({ type: 'create', ext, tt })
    } else if (!cell.is_default) {
      setPanel({ type: 'edit', cell })
    } else {
      setPanel({ type: 'create', ext, tt })
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Profile Matrix</h1>
          <p className="text-gray-500 text-sm mt-0.5">Processing profile override matrix</p>
        </div>
        <button
          onClick={() => setPanel({ type: 'add' })}
          className="px-3 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 transition-colors"
        >
          + Add override
        </button>
      </div>

      <div className="flex gap-3 flex-wrap">
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[90px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Extensions</div>
          <div className="text-base font-bold text-gray-700">{extensions.length}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[90px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Overrides</div>
          <div className={`text-base font-bold ${overrideCount > 0 ? 'text-violet-600' : 'text-gray-400'}`}>{overrideCount}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-center min-w-[90px]">
          <div className="text-[10px] font-bold uppercase text-gray-400">Unavailable</div>
          <div className={`text-base font-bold ${unavailableCount > 0 ? 'text-red-500' : 'text-gray-400'}`}>{unavailableCount}</div>
        </div>
      </div>

      <div className="flex gap-3 flex-wrap items-center">
        <input type="text" placeholder="Filter extension…" value={search} onChange={(e) => setSearch(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 w-48" />
        {selectedExt && (
          <button onClick={() => setSelectedExt(null)} className="text-xs text-brand hover:underline">
            Clear filter
          </button>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-xs border border-gray-200 rounded-lg overflow-hidden bg-white">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider text-gray-400 sticky left-0 bg-gray-50">
                Extension
              </th>
              {taskTypes.map((tt) => (
                <th key={tt} className="px-3 py-2 text-center text-[10px] font-bold uppercase tracking-wider text-gray-400 whitespace-nowrap">
                  {tt}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredExts.map((ext) => (
              <tr key={ext} className="border-b border-gray-100 last:border-0 hover:bg-gray-50 transition-colors">
                <td className="px-3 py-2 sticky left-0 bg-white font-mono text-gray-700 font-medium">
                  <button onClick={() => setSelectedExt(ext === selectedExt ? null : ext)} className="hover:text-brand">
                    {ext}
                  </button>
                </td>
                {taskTypes.map((tt) => {
                  const cell = cells[`${ext}.${tt}`]
                  const isOverride = cell && !cell.is_default
                  return (
                    <td key={tt} className="px-3 py-2 text-center">
                      <button
                        onClick={() => openCell(ext, tt)}
                        className={`w-full flex flex-col items-center gap-0.5 rounded p-1 transition-colors ${
                          isOverride
                            ? 'hover:bg-violet-50 ring-1 ring-violet-200'
                            : cell
                            ? 'hover:bg-blue-50'
                            : 'hover:bg-gray-50'
                        }`}
                        title={isOverride ? 'Edit override' : cell ? 'Create override for this cell' : 'Create override'}
                      >
                        {cell ? (
                          <>
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${kindColor(cell.kind)}`}>
                              {cell.kind === 'deterministic' ? 'det' : 'llm'}
                            </span>
                            <span className="text-[10px] font-mono text-gray-500 truncate max-w-[80px]" title={cell.provider}>
                              {cell.provider}
                            </span>
                            <span className={`text-[9px] px-1 rounded ${isOverride ? statusColor(cell.status) : 'text-gray-400'}`}>
                              {isOverride ? cell.status : 'default'}
                            </span>
                          </>
                        ) : (
                          <span className="text-gray-200 text-base leading-none">+</span>
                        )}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-gray-400">
        Click any cell to create or edit an override. Override cells are highlighted with a violet ring.
        Default cells show the built-in profile; creating an override replaces it for this workspace.
      </p>

      {panel?.type === 'edit' && (
        <EditPanel cell={panel.cell} onClose={() => setPanel(null)} />
      )}
      {panel?.type === 'create' && (
        <CreatePanel ext={panel.ext} tt={panel.tt} onClose={() => setPanel(null)} />
      )}
      {panel?.type === 'add' && (
        <AddPanel extensions={extensions} onClose={() => setPanel(null)} />
      )}
    </div>
  )
}
