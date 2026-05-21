import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'

const MEMBERS = [
  { id: 'u1', name: 'Platform Admin', role: 'owner', mfa: 'enabled', last: 'today' },
  { id: 'u2', name: 'Retrieval Engineer', role: 'editor', mfa: 'enabled', last: 'yesterday' },
  { id: 'u3', name: 'Audit Reader', role: 'viewer', mfa: 'pending', last: '7d ago' },
]

const KEYS = [
  { id: 'key-console', name: 'console-admin-key', scope: 'admin:*', last: '2h ago' },
  { id: 'key-openai', name: 'openai-compatible-client', scope: 'answer:read, retrieval:run', last: '1d ago' },
]

export default function Access() {
  const [message, setMessage] = useState('')
  return (
    <ConsolePage title="Access" description="Workspace members, invites, API keys, and enterprise auth policy.">
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Members" actions={<Button onClick={() => setMessage('Invite form opened for a new workspace member.')}>Invite member</Button>}>
          <DataTable
            rows={MEMBERS}
            getKey={(row) => row.id}
            columns={[
              { key: 'name', label: 'Member', render: (row) => row.name },
              { key: 'role', label: 'Role', render: (row) => row.role },
              { key: 'mfa', label: 'MFA', render: (row) => <StatusPill tone={row.mfa === 'enabled' ? 'ok' : 'warn'}>{row.mfa}</StatusPill> },
              { key: 'last', label: 'Last active', render: (row) => row.last },
            ]}
          />
        </Panel>
        <Panel title="API keys" actions={<Button onClick={() => setMessage('API key creation flow opened.')}>Create key</Button>}>
          <DataTable
            rows={KEYS}
            getKey={(row) => row.id}
            columns={[
              { key: 'name', label: 'Key', render: (row) => row.name },
              { key: 'scope', label: 'Scope', render: (row) => <span className="font-mono text-xs">{row.scope}</span> },
              { key: 'last', label: 'Last used', render: (row) => row.last },
            ]}
          />
        </Panel>
      </div>
      <Panel title="Enterprise auth" description="OIDC, LDAP, and MFA are managed with access policy.">
        <div className="grid gap-3 sm:grid-cols-3">
          {['OIDC: configured', 'LDAP: optional', 'MFA: required for admins'].map((item) => (
            <div key={item} className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm text-slate-700">{item}</div>
          ))}
        </div>
      </Panel>
    </ConsolePage>
  )
}
