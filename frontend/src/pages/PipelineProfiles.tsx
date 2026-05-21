import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'

type Step = { id: string; name: string; engine: string; required: boolean }
type Profile = { id: string; format: string; version: string; impact: string; steps: Step[] }

const STEP_OPTIONS = ['Parser', 'OCR', 'Table extraction', 'LLM cleaning', 'Sanitizer', 'Chunker', 'Embedding', 'Evaluation gate', 'Export']

const INITIAL_PROFILES: Profile[] = [
  { id: 'pdf', format: 'PDF', version: 'v18', impact: '12.4k docs', steps: [
    { id: 'pdf-parse', name: 'Parser', engine: 'docling', required: true },
    { id: 'pdf-clean', name: 'LLM cleaning', engine: 'gpt-4.1-mini', required: false },
    { id: 'pdf-sanitize', name: 'Sanitizer', engine: 'strict profile', required: true },
    { id: 'pdf-embed', name: 'Embedding', engine: 'voyage-3-large', required: true },
  ] },
  { id: 'csv', format: 'CSV', version: 'v9', impact: '1.8k docs', steps: [
    { id: 'csv-parse', name: 'Parser', engine: 'streaming csv', required: true },
    { id: 'csv-table', name: 'Table extraction', engine: 'header inference', required: true },
    { id: 'csv-embed', name: 'Embedding', engine: 'text-embedding-3-small', required: true },
  ] },
]

export default function PipelineProfiles() {
  const [profiles, setProfiles] = useState(INITIAL_PROFILES)
  const [selectedId, setSelectedId] = useState(INITIAL_PROFILES[0].id)
  const [newStep, setNewStep] = useState('LLM cleaning')
  const [message, setMessage] = useState('')
  const selected = profiles.find((profile) => profile.id === selectedId) ?? profiles[0]

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
                onClick={() => setSelectedId(profile.id)}
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
              { key: 'engine', label: 'Engine', render: (row) => <span className="font-mono text-xs text-slate-600">{row.engine}</span> },
              { key: 'required', label: 'Mode', render: (row) => <StatusPill tone={row.required ? 'info' : 'neutral'}>{row.required ? 'Required' : 'Optional'}</StatusPill> },
              { key: 'actions', label: 'Actions', align: 'right', render: (row) => <button onClick={() => removeStep(row.id)} className="rounded-lg border border-line px-2 py-1 text-xs text-slate-600 hover:bg-blue-50">Remove</button> },
            ]}
          />
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {['History: v18 current, v17 previous', 'Diff: sanitizer stricter on CSV exports', 'Rollback: restore previous version with audit event'].map((item) => (
              <div key={item} className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-xs text-slate-600">{item}</div>
            ))}
          </div>
        </Panel>
      </div>
    </ConsolePage>
  )
}
