import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'

const JOBS = [
  { id: 'backup', name: 'Backup', schedule: 'daily 02:00', last: 'completed', target: 'object storage', output: 'snapshot manifest, restore point, artifact checksum' },
  { id: 'retention', name: 'Retention sweep', schedule: 'weekly', last: 'completed', target: 'audit + artifacts', output: 'deleted 128 expired artifacts, preserved 12 audit holds' },
  { id: 'graph-rehearsal', name: 'Graph console rehearsal', schedule: 'before demo', last: 'completed', target: 'KG Lite demo loop', output: 'graph context rendered, relation feedback suppressed, smoke runbook passed, cleanup complete' },
  { id: 'sqlite', name: 'SQLite warning check', schedule: 'on deploy', last: 'pass', target: 'runtime config', output: 'production DATABASE_URL is external Postgres' },
  { id: 'diagnostics', name: 'Health diagnostics', schedule: 'manual', last: 'degraded', target: 'API / DB / vector', output: 'qdrant optional service unavailable, fallback pgvector active' },
]

const AUDIT = [
  { id: 'a1', time: '10:24', actor: 'platform-admin', event: 'backup.run', result: 'success' },
  { id: 'a4', time: '10:11', actor: 'graph-demo-bot', event: 'graph_console.rehearsal', result: 'success' },
  { id: 'a5', time: '10:08', actor: 'curator', event: 'relation_feedback.suppress', result: 'recorded' },
  { id: 'a2', time: '09:51', actor: 'retrieval-engineer', event: 'profile.rollback.preview', result: 'recorded' },
  { id: 'a3', time: '09:32', actor: 'system', event: 'retention.sweep', result: 'success' },
]

export default function Operations() {
  const [message, setMessage] = useState('')
  const [selectedJobId, setSelectedJobId] = useState(JOBS[0].id)
  const selectedJob = JOBS.find((job) => job.id === selectedJobId) ?? JOBS[0]
  return (
    <ConsolePage title="Operations" description="Backup, retention, diagnostics, and operational audit actions.">
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Panel title="Operational jobs" description="Click a row to inspect the latest output before running the job.">
          <DataTable
            rows={JOBS}
            getKey={(row) => row.id}
            onRowClick={(row) => setSelectedJobId(row.id)}
            columns={[
              { key: 'name', label: 'Job', render: (row) => <div className="font-medium text-ink">{row.name}</div> },
              { key: 'schedule', label: 'Schedule', render: (row) => row.schedule },
              { key: 'target', label: 'Target', render: (row) => row.target },
              { key: 'last', label: 'Last result', render: (row) => <StatusPill tone={row.last === 'degraded' ? 'warn' : 'ok'}>{row.last}</StatusPill> },
              { key: 'actions', label: 'Actions', align: 'right', render: (row) => <Button variant="secondary" onClick={() => setMessage(`${row.name} queued.`)}>Run</Button> },
            ]}
          />
        </Panel>
        <Panel
          title={`${selectedJob.name} detail`}
          description={`${selectedJob.target} · ${selectedJob.schedule}`}
          actions={<Button onClick={() => setMessage(`${selectedJob.name} run started and audit event created.`)}>Run now</Button>}
        >
          <div className="rounded-lg border border-line bg-white p-3">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted">Latest output</div>
            <div className="mt-2 font-mono text-xs text-slate-700">{selectedJob.output}</div>
          </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">Retry policy: 3 attempts</div>
            <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">Audit: required</div>
            <div className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm">Notify: ops route</div>
          </div>
          {selectedJob.id === 'graph-rehearsal' && (
            <div className="mt-3 rounded-lg border border-blue-100 bg-blue-50/45 p-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted">Rehearsal checklist</div>
              <div className="mt-2 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
                <div>Graph context visible in Retrieval Lab</div>
                <div>Incorrect relation suppressed after feedback</div>
                <div>Graph console smoke script passes</div>
                <div>Demo cleanup emits audit event</div>
              </div>
            </div>
          )}
        </Panel>
      </div>
      <Panel title="Audit trail" description="Recent administrative operations relevant to backup, retention, profiles, and diagnostics.">
        <DataTable
          rows={AUDIT}
          getKey={(row) => row.id}
          columns={[
            { key: 'time', label: 'Time', render: (row) => <span className="font-mono text-xs">{row.time}</span> },
            { key: 'actor', label: 'Actor', render: (row) => row.actor },
            { key: 'event', label: 'Event', render: (row) => <span className="font-mono text-xs">{row.event}</span> },
            { key: 'result', label: 'Result', render: (row) => <StatusPill tone={row.result === 'success' ? 'ok' : 'info'}>{row.result}</StatusPill> },
          ]}
        />
      </Panel>
    </ConsolePage>
  )
}
