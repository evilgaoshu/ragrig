import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'
import { SchemaModal, type SchemaSubmit } from '../components/SchemaModal'
import { NOTIFICATION_ROUTE_SCHEMAS } from './consoleSchemas'

type RouteRow = {
  id: string
  event: string
  channels: string
  condition: string
  severity: 'info' | 'warn' | 'critical'
}

const CHANNELS = [
  { name: 'Email', target: 'ops-alerts@company.com', status: 'verified' },
  { name: 'Feishu', target: 'RAG platform ops group', status: 'verified' },
  { name: 'Telegram', target: '@rag_ops_alerts', status: 'needs token' },
]

const INITIAL_ROUTES: RouteRow[] = [
  { id: 'route-pipeline', event: 'pipeline_failed', channels: 'email, feishu', condition: 'failure_count > 0', severity: 'critical' },
  { id: 'route-budget', event: 'budget_threshold', channels: 'email', condition: 'usage >= 80%', severity: 'warn' },
  { id: 'route-eval', event: 'evaluation_regression', channels: 'feishu, telegram', condition: 'faithfulness -5%', severity: 'warn' },
]

export default function Notifications() {
  const [routes, setRoutes] = useState(INITIAL_ROUTES)
  const [showModal, setShowModal] = useState(false)
  const [message, setMessage] = useState('')

  const addRoute = (payload: SchemaSubmit) => {
    setRoutes((current) => [
      {
        id: `route-${Date.now()}`,
        event: payload.values.event,
        channels: payload.values.channels,
        condition: payload.values.condition,
        severity: (payload.values.severity as RouteRow['severity']) || 'info',
      },
      ...current,
    ])
    setMessage('Notification route created.')
    setShowModal(false)
  }

  return (
    <ConsolePage
      title="Notifications"
      description="Route operational events to Email, Feishu, or Telegram. Tests belong to each channel; new routes are created from the routing table."
      actions={<Button onClick={() => setShowModal(true)}>New route</Button>}
    >
      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Panel title="Channels" description="Delivery endpoints and credentials.">
          <div className="space-y-3">
            {CHANNELS.map((channel) => (
              <div key={channel.name} className="rounded-lg border border-blue-100 bg-blue-50/45 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-medium text-ink">{channel.name}</div>
                    <div className="mt-0.5 text-xs text-muted">{channel.target}</div>
                  </div>
                  <StatusPill tone={channel.status === 'verified' ? 'ok' : 'warn'}>{channel.status}</StatusPill>
                </div>
                <button onClick={() => setMessage(`Test notification queued for ${channel.name}`)} className="mt-3 rounded-lg border border-line bg-white px-2 py-1 text-xs font-medium text-brand hover:bg-blue-50">
                  Send channel test
                </button>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Notification routing" description="Routes are event-specific, not a generic send-test control.">
          {message && <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
          <DataTable
            rows={routes}
            getKey={(row) => row.id}
            columns={[
              { key: 'event', label: 'Event', render: (row) => <span className="font-mono text-xs">{row.event}</span> },
              { key: 'condition', label: 'Condition', render: (row) => row.condition },
              { key: 'channels', label: 'Channels', render: (row) => row.channels },
              { key: 'severity', label: 'Severity', render: (row) => <StatusPill tone={row.severity === 'critical' ? 'danger' : row.severity === 'warn' ? 'warn' : 'info'}>{row.severity}</StatusPill> },
            ]}
          />
        </Panel>
      </div>
      {showModal && (
        <SchemaModal
          title="New notification route"
          schemas={NOTIFICATION_ROUTE_SCHEMAS}
          submitLabel="Create route"
          onClose={() => setShowModal(false)}
          onSubmit={addRoute}
        />
      )}
    </ConsolePage>
  )
}
