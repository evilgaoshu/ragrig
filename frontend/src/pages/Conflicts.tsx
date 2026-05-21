import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'

const INITIAL = [
  { id: 'c1', topic: 'Refund policy window', docs: 'handbook.md vs support-faq.md', severity: 'high', owner: 'support' },
  { id: 'c2', topic: 'Model retention defaults', docs: 'ops.md vs security.md', severity: 'medium', owner: 'platform' },
]

export default function Conflicts() {
  const [message, setMessage] = useState('')
  return (
    <ConsolePage title="Conflicts" description="Resolve contradictory knowledge before it reaches retrieval and answer generation.">
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
      <Panel title="Open conflicts">
        <DataTable
          rows={INITIAL}
          getKey={(row) => row.id}
          columns={[
            { key: 'topic', label: 'Topic', render: (row) => <div className="font-medium text-ink">{row.topic}</div> },
            { key: 'docs', label: 'Evidence', render: (row) => row.docs },
            { key: 'owner', label: 'Owner', render: (row) => row.owner },
            { key: 'severity', label: 'Severity', render: (row) => <StatusPill tone={row.severity === 'high' ? 'danger' : 'warn'}>{row.severity}</StatusPill> },
            { key: 'actions', label: 'Actions', align: 'right', render: (row) => <Button variant="secondary" onClick={() => setMessage(`Resolution workflow opened for ${row.topic}.`)}>Resolve</Button> },
          ]}
        />
      </Panel>
    </ConsolePage>
  )
}
