interface Props {
  label: string
  value: string | number
  sub?: string
  status?: 'ok' | 'error' | 'warn' | 'neutral'
}

const statusColor: Record<string, string> = {
  ok: 'text-emerald-600',
  error: 'text-red-500',
  warn: 'text-amber-500',
  neutral: 'text-gray-500',
}

export default function StatusCard({ label, value, sub, status = 'neutral' }: Props) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-0.5">
      <div className="text-[10px] font-bold uppercase tracking-wider text-gray-400">{label}</div>
      <strong className={`text-base font-bold ${statusColor[status]}`}>{value}</strong>
      {sub && <span className="text-[11px] text-gray-400 truncate">{sub}</span>}
    </div>
  )
}
