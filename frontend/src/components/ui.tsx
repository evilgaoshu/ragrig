/**
 * Shared form field and button primitives used across pages.
 */

import type { ReactNode } from 'react'

// ── Button ────────────────────────────────────────────────────────────────────

interface ButtonProps {
  type?: 'button' | 'submit' | 'reset'
  variant?: 'primary' | 'secondary' | 'ghost'
  disabled?: boolean
  onClick?: () => void
  children: ReactNode
  className?: string
}

export function Button({
  type = 'button',
  variant = 'primary',
  disabled,
  onClick,
  children,
  className = '',
}: ButtonProps) {
  const base =
    'px-4 py-2 text-sm font-medium rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed'
  const variants = {
    primary: 'bg-brand text-white hover:bg-brand/90',
    secondary: 'border border-gray-200 text-gray-600 hover:bg-gray-50',
    ghost: 'text-brand hover:underline',
  }
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`${base} ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

// ── TextField ─────────────────────────────────────────────────────────────────

interface TextFieldProps {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  hint?: string
  required?: boolean
  type?: 'text' | 'password' | 'url' | 'number'
}

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  hint,
  required,
  type = 'text',
}: TextFieldProps) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-gray-600">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40"
      />
      {hint && <p className="text-[11px] text-gray-400">{hint}</p>}
    </div>
  )
}

// ── TextArea ──────────────────────────────────────────────────────────────────

interface TextAreaProps {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  hint?: string
  rows?: number
}

export function TextArea({ label, value, onChange, placeholder, hint, rows = 4 }: TextAreaProps) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-gray-600">{label}</label>
      <textarea
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-xs font-mono resize-y focus:outline-none focus:ring-2 focus:ring-brand/40"
      />
      {hint && <p className="text-[11px] text-gray-400">{hint}</p>}
    </div>
  )
}

// ── SelectField ───────────────────────────────────────────────────────────────

interface SelectFieldProps {
  label: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}

export function SelectField({ label, value, onChange, options }: SelectFieldProps) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-gray-600">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}

// ── CheckField ────────────────────────────────────────────────────────────────

interface CheckFieldProps {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}

export function CheckField({ label, checked, onChange }: CheckFieldProps) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="rounded border-gray-300 text-brand focus:ring-brand/40"
      />
      <span className="text-xs text-gray-700">{label}</span>
    </label>
  )
}

// ── SectionDivider ────────────────────────────────────────────────────────────

export function SectionDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 pt-1">
      <div className="flex-1 border-t border-gray-100" />
      <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">{label}</span>
      <div className="flex-1 border-t border-gray-100" />
    </div>
  )
}

// ── ErrorBanner ───────────────────────────────────────────────────────────────

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
      {message}
    </div>
  )
}
