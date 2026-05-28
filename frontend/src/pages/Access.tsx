import { useState } from 'react'
import { Button } from '../components/ui'
import { ConsolePage, DataTable, Panel, StatusPill } from '../components/console'

type Member = { id: string; name: string; role: string; mfa: string; last: string }
type ApiKey = { id: string; name: string; scope: string; last: string }

const MEMBERS: Member[] = [
  { id: 'u1', name: 'Platform Admin', role: 'owner', mfa: 'enabled', last: 'today' },
  { id: 'u2', name: 'Retrieval Engineer', role: 'editor', mfa: 'enabled', last: 'yesterday' },
  { id: 'u3', name: 'Audit Reader', role: 'viewer', mfa: 'pending', last: '7d ago' },
]

const KEYS: ApiKey[] = [
  { id: 'key-console', name: 'console-admin-key', scope: 'admin:*', last: '2h ago' },
  { id: 'key-openai', name: 'openai-compatible-client', scope: 'answer:read, retrieval:run', last: '1d ago' },
]

export default function Access() {
  const [members, setMembers] = useState(MEMBERS)
  const [keys, setKeys] = useState(KEYS)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [keyOpen, setKeyOpen] = useState(false)
  const [message, setMessage] = useState('')
  return (
    <ConsolePage title="Access" description="Workspace members, invites, API keys, and enterprise auth policy.">
      {message && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-700">{message}</div>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Members" actions={<Button onClick={() => setInviteOpen(true)}>Invite member</Button>}>
          <DataTable
            rows={members}
            getKey={(row) => row.id}
            columns={[
              { key: 'name', label: 'Member', render: (row) => row.name },
              { key: 'role', label: 'Role', render: (row) => row.role },
              { key: 'mfa', label: 'MFA', render: (row) => <StatusPill tone={row.mfa === 'enabled' ? 'ok' : 'warn'}>{row.mfa}</StatusPill> },
              { key: 'last', label: 'Last active', render: (row) => row.last },
              { key: 'actions', label: 'Actions', align: 'right', render: (row) => <button onClick={() => setMessage(`Role editor opened for ${row.name}.`)} className="rounded-lg border border-line px-2 py-1 text-xs font-medium text-brand hover:bg-blue-50">Edit</button> },
            ]}
          />
        </Panel>
        <Panel title="API keys" actions={<Button onClick={() => setKeyOpen(true)}>Create key</Button>}>
          <DataTable
            rows={keys}
            getKey={(row) => row.id}
            columns={[
              { key: 'name', label: 'Key', render: (row) => row.name },
              { key: 'scope', label: 'Scope', render: (row) => <span className="font-mono text-xs">{row.scope}</span> },
              { key: 'last', label: 'Last used', render: (row) => row.last },
              { key: 'actions', label: 'Actions', align: 'right', render: (row) => <button onClick={() => setMessage(`Rotation flow opened for ${row.name}.`)} className="rounded-lg border border-line px-2 py-1 text-xs font-medium text-brand hover:bg-blue-50">Rotate</button> },
            ]}
          />
        </Panel>
      </div>
      <Panel title="Enterprise auth" description="OIDC, LDAP, and MFA are managed with access policy.">
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            { label: 'OIDC', state: 'configured', action: 'Edit OIDC' },
            { label: 'LDAP', state: 'optional', action: 'Configure LDAP' },
            { label: 'MFA', state: 'required for admins', action: 'Edit policy' },
          ].map((item) => (
            <div key={item.label} className="rounded-lg border border-blue-100 bg-blue-50/45 p-3 text-sm text-slate-700">
              <div className="font-medium text-ink">{item.label}</div>
              <div className="mt-1 text-xs text-muted">{item.state}</div>
              <button onClick={() => setMessage(`${item.action} form opened.`)} className="mt-3 rounded-lg border border-line bg-white px-2 py-1 text-xs font-medium text-brand hover:bg-blue-50">{item.action}</button>
            </div>
          ))}
        </div>
      </Panel>
      {inviteOpen && (
        <AccessForm
          title="Invite member"
          fields={[
            { name: 'email', label: 'Email', placeholder: 'admin@example.com' },
            { name: 'role', label: 'Role', placeholder: 'owner / editor / viewer' },
          ]}
          submitLabel="Send invite"
          onClose={() => setInviteOpen(false)}
          onSubmit={(values) => {
            setMembers((current) => [{ id: `u-${Date.now()}`, name: values.email, role: values.role || 'viewer', mfa: 'pending', last: 'invited' }, ...current])
            setMessage(`Invite sent to ${values.email}.`)
            setInviteOpen(false)
          }}
        />
      )}
      {keyOpen && (
        <AccessForm
          title="Create API key"
          fields={[
            { name: 'name', label: 'Key name', placeholder: 'retrieval-client-prod' },
            { name: 'scope', label: 'Scopes', placeholder: 'retrieval:run, answer:read' },
          ]}
          submitLabel="Create key"
          onClose={() => setKeyOpen(false)}
          onSubmit={(values) => {
            setKeys((current) => [{ id: `key-${Date.now()}`, name: values.name, scope: values.scope, last: 'never' }, ...current])
            setMessage(`API key ${values.name} created. Secret visible once in production flow.`)
            setKeyOpen(false)
          }}
        />
      )}
    </ConsolePage>
  )
}

function AccessForm({
  title,
  fields,
  submitLabel,
  onClose,
  onSubmit,
}: {
  title: string
  fields: Array<{ name: string; label: string; placeholder: string }>
  submitLabel: string
  onClose: () => void
  onSubmit: (values: Record<string, string>) => void
}) {
  const [values, setValues] = useState<Record<string, string>>({})
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/30 px-4 py-6">
      <form
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-line bg-white shadow-xl"
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit(values)
        }}
      >
        <div className="border-b border-line bg-blue-50/70 px-5 py-4">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          <p className="mt-1 text-xs text-muted">Prototype form. Required fields are enforced before submit.</p>
        </div>
        <div className="space-y-4 p-5">
          {fields.map((field) => (
            <label key={field.name} className="block space-y-1">
              <span className="text-xs font-medium text-slate-600">{field.label} <span className="rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] text-blue-700">Required</span></span>
              <input
                required
                value={values[field.name] ?? ''}
                placeholder={field.placeholder}
                onChange={(event) => setValues((current) => ({ ...current, [field.name]: event.target.value }))}
                className="w-full rounded-lg border border-line px-3 py-2 text-sm"
              />
            </label>
          ))}
        </div>
        <div className="flex justify-end gap-2 border-t border-line bg-slate-50 px-5 py-4">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit">{submitLabel}</Button>
        </div>
      </form>
    </div>
  )
}
