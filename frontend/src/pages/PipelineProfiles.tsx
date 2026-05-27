import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'

type Step = { id: string; name: string; engine: string; required: boolean }
type ProfileVersion = { id: string; version: string; author: string; date: string; summary: string; risk: 'low' | 'medium' | 'high' }
type Profile = { id: string; format: string; version: string; impact: string; steps: Step[]; history: ProfileVersion[] }

const STEP_OPTIONS = ['Parser', 'OCR', 'Table extraction', 'LLM cleaning', 'Sanitizer', 'Chunker', 'Embedding', 'Evaluation gate', 'Export']

const INITIAL_PROFILES: Profile[] = [
  { id: 'pdf', format: 'PDF', version: 'v18', impact: '12.4k docs', steps: [
    { id: 'pdf-parse', name: 'Parser', engine: 'docling', required: true },
    { id: 'pdf-clean', name: 'LLM cleaning', engine: 'gpt-4.1-mini', required: false },
    { id: 'pdf-sanitize', name: 'Sanitizer', engine: 'strict profile', required: true },
    { id: 'pdf-embed', name: 'Embedding', engine: 'voyage-3-large', required: true },
  ], history: [
    { id: 'pdf-v18', version: 'v18', author: 'Platform Admin', date: 'today', summary: 'Added optional LLM cleaning before sanitizer.', risk: 'medium' },
    { id: 'pdf-v17', version: 'v17', author: 'Ingestion Ops', date: '2d ago', summary: 'Switched parser from unstructured to docling.', risk: 'low' },
    { id: 'pdf-v16', version: 'v16', author: 'Security', date: '6d ago', summary: 'Enabled strict sanitizer profile for previews.', risk: 'high' },
  ] },
  { id: 'csv', format: 'CSV', version: 'v9', impact: '1.8k docs', steps: [
    { id: 'csv-parse', name: 'Parser', engine: 'streaming csv', required: true },
    { id: 'csv-table', name: 'Table extraction', engine: 'header inference', required: true },
    { id: 'csv-embed', name: 'Embedding', engine: 'text-embedding-3-small', required: true },
  ], history: [
    { id: 'csv-v9', version: 'v9', author: 'Data Ops', date: 'today', summary: 'Added oversized line guard before chunking.', risk: 'low' },
    { id: 'csv-v8', version: 'v8', author: 'Security', date: '5d ago', summary: 'Expanded CSV sanitizer golden coverage.', risk: 'medium' },
  ] },
]

export default function PipelineProfiles() {
  const [profiles, setProfiles] = useState(INITIAL_PROFILES)
  const [selectedId, setSelectedId] = useState(INITIAL_PROFILES[0].id)
  const [newStep, setNewStep] = useState('LLM cleaning')
  const [selectedVersionId, setSelectedVersionId] = useState(INITIAL_PROFILES[0].history[0].id)
  const [message, setMessage] = useState('')
  const selected = profiles.find((profile) => profile.id === selectedId) ?? profiles[0]
  const selectedVersion = selected.history.find((version) => version.id === selectedVersionId) ?? selected.history[0]

  const addStep = () => {
    setProfiles((current) =>
      current.map((profile) =>
        profile.id === selected.id
          ? { ...profile, steps: [...profile.steps, { id: `${profile.id}-${Date.now()}`, name: newStep, engine: 'configure engine', required: false }] }
          : profile,
      ),
    )
    setMessage(`${newStep} added to ${selected.format} pipeline.`)
  }

  const updateStepEngine = (stepId: string, engine: string) => {
    setProfiles((current) =>
      current.map((profile) =>
        profile.id === selected.id
          ? { ...profile, steps: profile.steps.map((step) => step.id === stepId ? { ...step, engine } : step) }
          : profile,
      ),
    )
  }

  const toggleStepMode = (stepId: string) => {
    setProfiles((current) =>
      current.map((profile) =>
        profile.id === selected.id
          ? { ...profile, steps: profile.steps.map((step) => step.id === stepId ? { ...step, required: !step.required } : step) }
          : profile,
      ),
    )
  }

  const removeStep = (stepId: string) => {
    setProfiles((current) =>
      current.map((profile) =>
        profile.id === selected.id ? { ...profile, steps: profile.steps.filter((step) => step.id !== stepId) } : profile,
      ),
    )
  }

  return (
    <ConsolePage
      title="Pipeline profiles"
      description="Format-specific processing pipelines with version history, diff, rollback, and preview impact."
      actions={<Button variant="secondary" onClick={() => setMessage(`Preview impact generated for ${selected.format}.`)}>Preview impact</Button>}
    >
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Panel title="Formats">
          <div className="space-y-2">
            {profiles.map((profile) => (
              <button
                key={profile.id}
                onClick={() => {
                  setSelectedId(profile.id)
                  setSelectedVersionId(profile.history[0].id)
                }}
                className={`w-full rounded-lg border px-3 py-2 text-left ${profile.id === selected.id ? 'border-brand bg-blue-50 text-brand' : 'border-line bg-white text-slate-600 hover:bg-blue-50'}`}
              >
                <div className="font-medium">{profile.format}</div>
                <div className="text-xs text-muted">{profile.version} · {profile.impact}</div>
              </button>
            ))}
          </div>
        </Panel>
        <Panel
          title={`${selected.format} processing chain`}
          description="Add, remove, and review ordered steps. LLM cleaning is a first-class optional step."
          actions={
            <>
              <select value={newStep} onChange={(event) => setNewStep(event.target.value)} className="h-9 rounded-lg border border-line bg-white px-2 text-sm">
                {STEP_OPTIONS.map((step) => <option key={step}>{step}</option>)}
              </select>
              <Button onClick={addStep}>Add step</Button>
            </>
          }
        >
          {message && <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
          <DataTable
            rows={selected.steps}
            getKey={(row) => row.id}
            columns={[
              { key: 'name', label: 'Step', render: (row) => <div className="font-medium text-ink">{row.name}</div> },
              { key: 'engine', label: 'Engine', render: (row) => (
                <input
                  value={row.engine}
                  onChange={(event) => updateStepEngine(row.id, event.target.value)}
                  className="w-full min-w-40 rounded-lg border border-line px-2 py-1 font-mono text-xs text-slate-600"
                />
              ) },
              { key: 'required', label: 'Mode', render: (row) => (
                <button onClick={() => toggleStepMode(row.id)}>
                  <StatusPill tone={row.required ? 'info' : 'neutral'}>{row.required ? 'Required' : 'Optional'}</StatusPill>
                </button>
              ) },
              { key: 'actions', label: 'Actions', align: 'right', render: (row) => <button onClick={() => removeStep(row.id)} className="rounded-lg border border-line px-2 py-1 text-xs text-slate-600 hover:bg-blue-50">Remove</button> },
            ]}
          />
        </Panel>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[360px_1fr]">
        <Panel title="Profile history" description="Select a version to inspect change impact and rollback options.">
          <div className="space-y-2">
            {selected.history.map((version) => (
              <button
                key={version.id}
                onClick={() => setSelectedVersionId(version.id)}
                className={`w-full rounded-lg border px-3 py-2 text-left ${version.id === selectedVersion.id ? 'border-brand bg-blue-50' : 'border-line bg-white hover:bg-blue-50/60'}`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="font-medium text-ink">{version.version}</div>
                  <StatusPill tone={version.risk === 'high' ? 'danger' : version.risk === 'medium' ? 'warn' : 'ok'}>{version.risk}</StatusPill>
                </div>
                <div className="mt-1 text-xs text-muted">{version.author} · {version.date}</div>
              </button>
            ))}
          </div>
        </Panel>
        <Panel
          title={`${selectedVersion.version} diff and rollout`}
          description={selectedVersion.summary}
          actions={
            <>
              <Button variant="secondary" onClick={() => setMessage(`Rollback plan generated for ${selected.format} ${selectedVersion.version}.`)}>Preview rollback</Button>
              <Button onClick={() => setMessage(`${selected.format} ${selectedVersion.version} rollback queued with audit event.`)}>Rollback</Button>
            </>
          }
        >
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted">Affected documents</div>
              <div className="mt-2 text-2xl font-semibold text-ink">{selected.impact}</div>
            </div>
            <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted">Reindex estimate</div>
              <div className="mt-2 text-2xl font-semibold text-ink">18 min</div>
            </div>
            <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted">Rollback safety</div>
              <div className="mt-2 text-2xl font-semibold text-ink">audit gated</div>
            </div>
          </div>
          <div className="mt-4 rounded-lg border border-line bg-white p-3 font-mono text-xs text-slate-600">
            + LLM cleaning step runs before sanitizer<br />
            + Preview sanitizer now blocks raw table cells with sensitive patterns<br />
            - Previous direct parser-to-chunker path disabled for this format
          </div>
        </Panel>
      </div>
    </ConsolePage>
  )
}
