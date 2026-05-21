import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'

const JOBS = [
  { id: 'backup', name: 'Backup', schedule: 'daily 02:00', last: 'completed', target: 'object storage' },
  { id: 'retention', name: 'Retention sweep', schedule: 'weekly', last: 'completed', target: 'audit + artifacts' },
  { id: 'sqlite', name: 'SQLite warning check', schedule: 'on deploy', last: 'pass', target: 'runtime config' },
  { id: 'diagnostics', name: 'Health diagnostics', schedule: 'manual', last: 'degraded', target: 'API / DB / vector' },
]

export default function Operations() {
  const [message, setMessage] = useState('')
  return (
    <ConsolePage title="Operations" description="Backup, retention, diagnostics, and operational audit actions.">
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
      <Panel title="Operational jobs">
        <DataTable
          rows={JOBS}
          getKey={(row) => row.id}
          columns={[
            { key: 'name', label: 'Job', render: (row) => row.name },
            { key: 'schedule', label: 'Schedule', render: (row) => row.schedule },
            { key: 'target', label: 'Target', render: (row) => row.target },
            { key: 'last', label: 'Last result', render: (row) => <StatusPill tone={row.last === 'degraded' ? 'warn' : 'ok'}>{row.last}</StatusPill> },
            { key: 'actions', label: 'Actions', align: 'right', render: (row) => <Button variant="secondary" onClick={() => setMessage(`${row.name} queued.`)}>Run {row.name}</Button> },
          ]}
        />
      </Panel>
    </ConsolePage>
  )
}
