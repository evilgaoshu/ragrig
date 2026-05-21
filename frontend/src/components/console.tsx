import type { ReactNode } from 'react'

type StatusTone = 'ok' | 'warn' | 'danger' | 'info' | 'neutral'

const toneClasses: Record<StatusTone, string> = {
  ok: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  warn: 'border-amber-200 bg-amber-50 text-amber-700',
  danger: 'border-red-200 bg-red-50 text-red-700',
  info: 'border-blue-200 bg-blue-50 text-blue-700',
  neutral: 'border-slate-200 bg-slate-50 text-slate-600',
}

export function ConsolePage({
  title,
  description,
  actions,
  children,
}: {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="mx-auto max-w-[1500px] space-y-5 px-4 py-5 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[30px] font-semibold leading-tight tracking-[-0.02em] text-ink">
            {title}
          </h1>
          {description && <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}

export function Panel({
  title,
  description,
  actions,
  children,
  className = '',
}: {
  title?: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`overflow-hidden rounded-xl border border-line bg-panel ${className}`}>
      {(title || description || actions) && (
        <div className="flex min-h-14 items-center justify-between gap-3 border-b border-line bg-blue-50/45 px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function MetricCard({
  label,
  value,
  sub,
  tone = 'info',
}: {
  label: string
  value: ReactNode
  sub?: string
  tone?: StatusTone
}) {
  const border = tone === 'ok' ? 'border-t-emerald-400' : tone === 'warn' ? 'border-t-amber-400' : tone === 'danger' ? 'border-t-red-400' : 'border-t-brand'
  return (
    <div className={`rounded-xl border border-line border-t-2 ${border} bg-panel p-4`}>
      <div className="flex items-center justify-between gap-3 text-xs text-muted">
        <span>{label}</span>
      </div>
      <div className="mt-3 text-2xl font-semibold tracking-[-0.02em] text-ink">{value}</div>
      {sub && <div className="mt-2 text-xs text-muted">{sub}</div>}
    </div>
  )
}

export function StatusPill({ children, tone = 'neutral' }: { children: ReactNode; tone?: StatusTone }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${toneClasses[tone]}`}>
      {children}
    </span>
  )
}

export function DataTable<T>({
  columns,
  rows,
  getKey,
  onRowClick,
}: {
  columns: Array<{ key: string; label: string; render: (row: T) => ReactNode; align?: 'left' | 'right' }>
  rows: T[]
  getKey: (row: T) => string
  onRowClick?: (row: T) => void
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="min-w-full border-collapse text-sm">
        <thead className="bg-blue-50/70">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className={`border-b border-line px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-muted ${
                  column.align === 'right' ? 'text-right' : 'text-left'
                }`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={getKey(row)}
              onClick={() => onRowClick?.(row)}
              className={onRowClick ? 'cursor-pointer border-b border-line last:border-0 hover:bg-blue-50/40' : 'border-b border-line last:border-0'}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`px-3 py-3 align-top ${column.align === 'right' ? 'text-right' : 'text-left'}`}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
