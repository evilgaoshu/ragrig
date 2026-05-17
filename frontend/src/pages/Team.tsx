import { useState } from 'react'
import { useAuth } from '../contexts/useAuth'
import {
  useWorkspaceMembers,
  useUpdateMemberRole,
  useRemoveMember,
  useWorkspaceInvitations,
  useCreateInvitation,
  useRevokeInvitation,
} from '../api/hooks'
import type { WorkspaceMember, WorkspaceInvitation } from '../api/hooks'

const ROLES = ['owner', 'admin', 'editor', 'viewer'] as const
type Role = typeof ROLES[number]

function roleBadge(role: string) {
  const map: Record<string, string> = {
    owner: 'bg-indigo-100 text-indigo-700',
    admin: 'bg-purple-100 text-purple-700',
    editor: 'bg-emerald-100 text-emerald-700',
    viewer: 'bg-gray-100 text-gray-600',
  }
  return map[role] ?? 'bg-gray-100 text-gray-500'
}

// ── Member row ─────────────────────────────────────────────────────────────

function MemberRow({ member, isSelf, canManage, canAssignOwner }: {
  member: WorkspaceMember
  isSelf: boolean
  canManage: boolean
  canAssignOwner: boolean
}) {
  const updateRole = useUpdateMemberRole()
  const removeMember = useRemoveMember()
  const [editing, setEditing] = useState(false)
  const [newRole, setNewRole] = useState(member.role)

  const handleRoleChange = async () => {
    await updateRole.mutateAsync({ userId: member.user_id, role: newRole })
    setEditing(false)
  }

  const handleRemove = async () => {
    if (!confirm(`Remove ${member.display_name ?? member.email ?? 'this member'} from the workspace?`)) return
    await removeMember.mutateAsync(member.user_id)
  }

  const availableRoles = canAssignOwner ? ROLES : ROLES.filter((r) => r !== 'owner')

  return (
    <tr className="border-b border-gray-100 last:border-0">
      <td className="px-4 py-3">
        <div className="text-sm font-medium text-gray-800">
          {member.display_name ?? '—'}
          {isSelf && <span className="ml-1.5 text-[10px] text-gray-400">(you)</span>}
        </div>
        <div className="text-xs text-gray-400">{member.email ?? '—'}</div>
      </td>
      <td className="px-4 py-3">
        {editing ? (
          <div className="flex items-center gap-2">
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
              className="text-xs border border-gray-200 rounded px-2 py-1 bg-white focus:outline-none"
            >
              {availableRoles.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <button
              onClick={handleRoleChange}
              disabled={updateRole.isPending || newRole === member.role}
              className="text-xs px-2 py-1 bg-brand text-white rounded hover:bg-brand/90 disabled:opacity-40 transition-colors"
            >
              {updateRole.isPending ? '…' : 'Save'}
            </button>
            <button
              onClick={() => { setEditing(false); setNewRole(member.role) }}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              Cancel
            </button>
          </div>
        ) : (
          <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${roleBadge(member.role)}`}>
            {member.role}
          </span>
        )}
      </td>
      <td className="px-4 py-3">
        {canManage && !isSelf && (
          <div className="flex gap-2">
            {!editing && (
              <button
                onClick={() => setEditing(true)}
                className="text-xs text-brand hover:underline"
              >
                Change role
              </button>
            )}
            <button
              onClick={handleRemove}
              disabled={removeMember.isPending}
              className="text-xs text-red-500 hover:underline disabled:opacity-40"
            >
              Remove
            </button>
          </div>
        )}
      </td>
    </tr>
  )
}

// ── Invite modal ───────────────────────────────────────────────────────────

function InviteModal({ canAssignOwner, onClose }: { canAssignOwner: boolean; onClose: () => void }) {
  const createInvitation = useCreateInvitation()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('editor')
  const [days, setDays] = useState(7)
  const [result, setResult] = useState<WorkspaceInvitation | null>(null)
  const [copied, setCopied] = useState(false)

  const availableRoles = canAssignOwner ? ROLES : ROLES.filter((r) => r !== 'owner')

  const inviteLink = result?.token
    ? `${window.location.origin}/app/login?token=${result.token}`
    : null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const res = await createInvitation.mutateAsync({
      email: email.trim() || undefined,
      role,
      days,
    })
    setResult(res)
  }

  const copyLink = () => {
    if (!inviteLink) return
    navigator.clipboard.writeText(inviteLink).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-sm font-bold text-gray-900">Invite team member</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
        </div>

        {result ? (
          <div className="p-6 space-y-4">
            <div className="text-sm text-gray-700">
              Invitation created
              {result.email ? ` for ${result.email}` : ''}.
              {!result.email && ' Share this link with your teammate:'}
            </div>
            {inviteLink && (
              <div className="space-y-2">
                <div className="text-xs font-medium text-gray-600">Registration link</div>
                <div className="flex gap-2 items-center">
                  <code className="flex-1 text-[11px] bg-gray-100 rounded px-2 py-1.5 font-mono text-gray-700 break-all">
                    {inviteLink}
                  </code>
                  <button
                    onClick={copyLink}
                    className="shrink-0 text-xs px-2 py-1 border border-gray-200 rounded hover:bg-gray-50 transition-colors"
                  >
                    {copied ? '✓' : 'Copy'}
                  </button>
                </div>
                <p className="text-[11px] text-gray-400">
                  Expires in {days} day{days !== 1 ? 's' : ''}. The link can only be used once.
                  {result.email && ' An email was attempted if SMTP is configured.'}
                </p>
              </div>
            )}
            <button
              onClick={onClose}
              className="mt-2 px-4 py-2 bg-brand text-white text-sm rounded-lg hover:bg-brand/90 transition-colors"
            >
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-600">Email (optional)</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="teammate@example.com"
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40"
              />
              <p className="text-[11px] text-gray-400">
                Leave blank to generate a link without pre-assigning an email.
                If SMTP is configured, an invitation email will be sent automatically.
              </p>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-600">Role</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
              >
                {availableRoles.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-600">Expires in</label>
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
              >
                {[1, 3, 7, 14, 30].map((d) => (
                  <option key={d} value={d}>{d} day{d !== 1 ? 's' : ''}</option>
                ))}
              </select>
            </div>

            {createInvitation.isError && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
                {createInvitation.error?.message}
              </div>
            )}

            <div className="flex gap-3 pt-1">
              <button
                type="submit"
                disabled={createInvitation.isPending}
                className="px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 disabled:opacity-40 transition-colors"
              >
                {createInvitation.isPending ? 'Creating…' : 'Create invitation'}
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
      </div>
    </div>
  )
}

// ── Invitation row ─────────────────────────────────────────────────────────

function InvitationRow({ inv }: { inv: WorkspaceInvitation }) {
  const revoke = useRevokeInvitation()
  const expiresAt = new Date(inv.expires_at)
  const isExpired = expiresAt < new Date()

  return (
    <tr className="border-b border-gray-100 last:border-0">
      <td className="px-4 py-3 text-sm text-gray-700">{inv.email ?? <span className="text-gray-400">—</span>}</td>
      <td className="px-4 py-3">
        <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${roleBadge(inv.role)}`}>
          {inv.role}
        </span>
      </td>
      <td className="px-4 py-3 text-xs text-gray-500">
        {isExpired ? (
          <span className="text-red-500">Expired {expiresAt.toLocaleDateString()}</span>
        ) : (
          `Expires ${expiresAt.toLocaleDateString()}`
        )}
      </td>
      <td className="px-4 py-3">
        <button
          onClick={() => revoke.mutate(inv.id)}
          disabled={revoke.isPending}
          className="text-xs text-red-500 hover:underline disabled:opacity-40"
        >
          Revoke
        </button>
      </td>
    </tr>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function Team() {
  const { user } = useAuth()
  const { data: members, isLoading: membersLoading } = useWorkspaceMembers()
  const { data: invitations, isLoading: invLoading } = useWorkspaceInvitations()
  const [showInvite, setShowInvite] = useState(false)

  const myRole = user?.role ?? 'viewer'
  const canManage = myRole === 'admin' || myRole === 'owner'
  const canAssignOwner = myRole === 'owner'

  return (
    <div className="p-6 space-y-8 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Team</h1>
          <p className="text-gray-500 text-sm mt-0.5">Workspace members and invitations</p>
        </div>
        {canManage && (
          <button
            onClick={() => setShowInvite(true)}
            className="px-3 py-1.5 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand/90 transition-colors"
          >
            + Invite member
          </button>
        )}
      </div>

      {/* Members */}
      <div>
        <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3">Members</h2>
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          {membersLoading ? (
            <div className="p-6 text-gray-400 text-sm">Loading…</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">User</th>
                  <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Role</th>
                  <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody>
                {(members ?? []).map((m) => (
                  <MemberRow
                    key={m.user_id}
                    member={m}
                    isSelf={m.user_id === user?.user_id}
                    canManage={canManage}
                    canAssignOwner={canAssignOwner}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Role reference */}
      <div>
        <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3">Role reference</h2>
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          {[
            { role: 'owner', desc: 'Full access including member management and role assignment' },
            { role: 'admin', desc: 'Can manage members (except owner) and all write operations' },
            { role: 'editor', desc: 'Can write to knowledge bases, run pipelines, upload documents' },
            { role: 'viewer', desc: 'Read-only access' },
          ].map((r) => (
            <div key={r.role} className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-100 last:border-0">
              <span className={`shrink-0 text-[11px] font-bold px-1.5 py-0.5 rounded w-16 text-center ${roleBadge(r.role)}`}>
                {r.role}
              </span>
              <span className="text-xs text-gray-600">{r.desc}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Pending invitations */}
      {canManage && (
        <div>
          <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3">
            Pending invitations
          </h2>
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            {invLoading ? (
              <div className="p-4 text-gray-400 text-sm">Loading…</div>
            ) : !invitations?.length ? (
              <div className="p-4 text-gray-400 text-sm">No pending invitations.</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Email</th>
                    <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Role</th>
                    <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Expiry</th>
                    <th className="text-left px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {invitations.map((inv) => (
                    <InvitationRow key={inv.id} inv={inv} />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {showInvite && (
        <InviteModal
          canAssignOwner={canAssignOwner}
          onClose={() => setShowInvite(false)}
        />
      )}
    </div>
  )
}
