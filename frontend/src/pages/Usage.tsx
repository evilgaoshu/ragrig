import { useEffect, useState } from 'react'
import {
  useBudget,
  useDeleteBudget,
  useUpsertBudget,
  useUsage,
  useUsageTimeseries,
  type UsageDaily,
} from '../api/hooks'

const GROUP_OPTIONS = [
  { value: '', label: 'Totals only' },
  { value: 'operation', label: 'By operation' },
  { value: 'model', label: 'By model' },
  { value: 'user', label: 'By user' },
]

function formatUSD(v: number): string {
  if (v === 0) return '$0.00'
  if (v < 0.01) return `$${v.toFixed(6)}`
  return `$${v.toFixed(4)}`
}

function formatInt(v: number): string {
  return v.toLocaleString()
}

function Sparkline({ data, height = 80 }: { data: UsageDaily[]; height?: number }) {
  const width = 600
  const padding = { top: 10, right: 10, bottom: 18, left: 36 }
  const innerW = width - padding.left - padding.right
  const innerH = height - padding.top - padding.bottom

  const points = data
  const max = Math.max(0.0000001, ...points.map((p) => p.cost_usd))
  const stepX = points.length > 1 ? innerW / (points.length - 1) : innerW

  const path = points
    .map((p, i) => {
      const x = padding.left + i * stepX
      const y = padding.top + innerH - (p.cost_usd / max) * innerH
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
      <line
        x1={padding.left}
        x2={width - padding.right}
        y1={padding.top + innerH}
        y2={padding.top + innerH}
        stroke="#e5e7eb"
      />
      <text x={padding.left - 4} y={padding.top + 4} fontSize="9" textAnchor="end" fill="#9ca3af">
        {formatUSD(max)}
      </text>
      <text
        x={padding.left - 4}
        y={padding.top + innerH + 3}
        fontSize="9"
        textAnchor="end"
        fill="#9ca3af"
      >
        $0
      </text>
      {points.length > 0 && (
        <path d={path} fill="none" stroke="#2563eb" strokeWidth="1.5" />
      )}
      {points.map((p, i) => {
        const x = padding.left + i * stepX
        const y = padding.top + innerH - (p.cost_usd / max) * innerH
        return (
          <g key={p.day}>
            <circle cx={x} cy={y} r="2.5" fill="#2563eb">
              <title>{`${p.day}: ${formatUSD(p.cost_usd)} · ${formatInt(p.tokens)} tokens`}</title>
            </circle>
            {(i === 0 || i === points.length - 1) && (
              <text
                x={x}
                y={padding.top + innerH + 14}
                fontSize="9"
                fill="#9ca3af"
                textAnchor={i === 0 ? 'start' : 'end'}
              >
                {p.day.slice(5)}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

function BudgetGauge({ used, limit }: { used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(1, used / limit) : 0
  const stroke = pct >= 1 ? '#dc2626' : pct >= 0.8 ? '#f59e0b' : '#16a34a'
  const radius = 48
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - pct)
  return (
    <svg width="120" height="120" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r={radius} stroke="#e5e7eb" strokeWidth="8" fill="none" />
      <circle
        cx="60"
        cy="60"
        r={radius}
        stroke={stroke}
        strokeWidth="8"
        fill="none"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 60 60)"
      />
      <text x="60" y="58" textAnchor="middle" fontSize="18" fontWeight="700" fill="#111827">
        {(pct * 100).toFixed(0)}%
      </text>
      <text x="60" y="76" textAnchor="middle" fontSize="10" fill="#6b7280">
        of monthly cap
      </text>
    </svg>
  )
}

export default function Usage() {
  const [groupBy, setGroupBy] = useState<string>('')
  const [days, setDays] = useState(30)
  const { data: usage, isLoading: usageLoading } = useUsage({
    group_by: groupBy || undefined,
  })
  const { data: timeseries } = useUsageTimeseries(days)
  const { data: budget } = useBudget()
  const upsert = useUpsertBudget()
  const del = useDeleteBudget()

  const [limit, setLimit] = useState<string>('')
  const [threshold, setThreshold] = useState<string>('80')
  const [hardCap, setHardCap] = useState(false)

  // Sync form when budget loads
  useEffect(() => {
    if (budget) {
      setLimit(String(budget.limit_usd))
      setThreshold(String(budget.alert_threshold_pct))
      setHardCap(budget.hard_cap)
    }
  }, [budget])

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    const n = Number(limit)
    if (!n || n <= 0) return
    upsert.mutate({
      limit_usd: n,
      alert_threshold_pct: Number(threshold) || 80,
      hard_cap: hardCap,
    })
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-bold text-gray-900">Usage &amp; Budget</h1>
        <p className="text-gray-500 text-sm mt-0.5">
          Token, cost, and latency rollups · per-workspace monthly budget
        </p>
      </div>

      {/* Top-line totals */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Events', value: formatInt(usage?.event_count ?? 0) },
          { label: 'Total tokens', value: formatInt(usage?.total_tokens ?? 0) },
          { label: 'Cost (USD)', value: formatUSD(usage?.cost_usd ?? 0) },
          {
            label: 'Avg latency',
            value: `${Math.round(usage?.avg_latency_ms ?? 0)} ms`,
          },
        ].map((m) => (
          <div key={m.label} className="rounded-lg border border-gray-200 bg-white p-3">
            <div className="text-[10px] uppercase tracking-wider text-gray-500">{m.label}</div>
            <div className="text-lg font-bold text-gray-900 mt-1">{m.value}</div>
          </div>
        ))}
      </div>

      {/* Budget */}
      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-800">Monthly budget</h2>
          {budget && (
            <button
              type="button"
              onClick={() => {
                if (confirm('Remove the budget?')) del.mutate()
              }}
              className="text-[11px] text-gray-500 hover:text-red-500"
            >
              remove
            </button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-6">
          <BudgetGauge used={usage?.cost_usd ?? 0} limit={budget?.limit_usd ?? 0} />
          <div className="flex-1 min-w-[260px]">
            {budget ? (
              <div className="text-[12px] text-gray-700 space-y-0.5">
                <div>
                  Spent <strong>{formatUSD(usage?.cost_usd ?? 0)}</strong> of{' '}
                  <strong>{formatUSD(budget.limit_usd)}</strong>
                </div>
                <div>
                  Alert at <strong>{budget.alert_threshold_pct}%</strong>
                  {budget.hard_cap && (
                    <span className="ml-2 px-1.5 py-0.5 bg-red-100 text-red-700 rounded">
                      hard cap — calls beyond limit are rejected
                    </span>
                  )}
                </div>
                {budget.last_alert_at && (
                  <div className="text-gray-500">
                    Last alert: {new Date(budget.last_alert_at).toLocaleString()}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-[12px] text-gray-400">
                No budget configured. Add one below — admins receive an email + webhook when the
                alert threshold is crossed (at most once per period).
              </div>
            )}
            <form onSubmit={handleSave} className="mt-3 grid grid-cols-3 gap-2 max-w-md">
              <label className="flex flex-col text-[11px] text-gray-600">
                Limit USD
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={limit}
                  onChange={(e) => setLimit(e.target.value)}
                  className="mt-0.5 border border-gray-300 rounded px-2 py-1 text-[12px]"
                />
              </label>
              <label className="flex flex-col text-[11px] text-gray-600">
                Alert %
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={threshold}
                  onChange={(e) => setThreshold(e.target.value)}
                  className="mt-0.5 border border-gray-300 rounded px-2 py-1 text-[12px]"
                />
              </label>
              <label className="flex items-center gap-1 text-[11px] text-gray-600 self-end pb-1">
                <input
                  type="checkbox"
                  checked={hardCap}
                  onChange={(e) => setHardCap(e.target.checked)}
                />
                Hard cap
              </label>
              <button
                type="submit"
                disabled={upsert.isPending}
                className="col-span-3 mt-1 rounded bg-brand text-white text-[12px] py-1.5 disabled:opacity-50"
              >
                {budget ? 'Update budget' : 'Create budget'}
              </button>
              {upsert.isError && (
                <div className="col-span-3 text-[11px] text-red-600">
                  {(upsert.error as Error).message}
                </div>
              )}
            </form>
          </div>
        </div>
      </section>

      {/* Daily series */}
      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-gray-800">Daily cost</h2>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="text-[11px] border border-gray-300 rounded px-2 py-0.5"
          >
            <option value="7">7d</option>
            <option value="30">30d</option>
            <option value="90">90d</option>
          </select>
        </div>
        {timeseries && timeseries.length > 0 ? (
          <Sparkline data={timeseries} />
        ) : (
          <div className="text-[12px] text-gray-400">
            No usage recorded yet. Issue some answers/retrievals first.
          </div>
        )}
      </section>

      {/* Group-by breakdown */}
      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-gray-800">Breakdown</h2>
          <select
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value)}
            className="text-[11px] border border-gray-300 rounded px-2 py-0.5"
          >
            {GROUP_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        {usageLoading && <div className="text-[11px] text-gray-400">Loading…</div>}
        {usage?.groups && usage.groups.length > 0 ? (
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-gray-200 text-[10px] uppercase tracking-wider text-gray-500">
                <th className="text-left py-1.5">Key</th>
                <th className="text-right py-1.5">Events</th>
                <th className="text-right py-1.5">Tokens</th>
                <th className="text-right py-1.5">Cost</th>
              </tr>
            </thead>
            <tbody>
              {usage.groups.map((g, i) => (
                <tr key={`${g.key}-${i}`} className="border-b border-gray-100">
                  <td className="py-1.5 font-mono text-[11px] text-gray-700">{g.key ?? '∅'}</td>
                  <td className="py-1.5 text-right">{formatInt(g.count)}</td>
                  <td className="py-1.5 text-right">
                    {formatInt(g.input_tokens + g.output_tokens)}
                  </td>
                  <td className="py-1.5 text-right">{formatUSD(g.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : groupBy ? (
          <div className="text-[11px] text-gray-400">No grouped data in this window.</div>
        ) : (
          <div className="text-[11px] text-gray-400">
            Select a grouping above to break down by operation, model, or user.
          </div>
        )}
      </section>
    </div>
  )
}
