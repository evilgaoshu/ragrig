import { useState } from 'react'
import { Button } from './ui'

export type FieldSchema = {
  name: string
  label: string
  type?: 'text' | 'password' | 'url' | 'number' | 'select' | 'textarea'
  required?: boolean
  placeholder?: string
  hint?: string
  options?: Array<{ value: string; label: string }>
}

export type ConnectorSchema = {
  id: string
  label: string
  description: string
  fields: FieldSchema[]
}

export type SchemaSubmit = {
  schemaId: string
  label: string
  values: Record<string, string>
}

export function SchemaModal({
  title,
  schemas,
  initialSchemaId,
  submitLabel = 'Create',
  onClose,
  onSubmit,
}: {
  title: string
  schemas: ConnectorSchema[]
  initialSchemaId?: string
  submitLabel?: string
  onClose: () => void
  onSubmit: (payload: SchemaSubmit) => void
}) {
  const [schemaId, setSchemaId] = useState(initialSchemaId ?? schemas[0]?.id ?? '')
  const schema = schemas.find((item) => item.id === schemaId) ?? schemas[0]
  const [values, setValues] = useState<Record<string, string>>({})

  const activeFields = schema?.fields ?? []

  const setValue = (name: string, value: string) => {
    setValues((current) => ({ ...current, [name]: value }))
  }

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    const missing = activeFields.find((field) => field.required && !values[field.name]?.trim())
    if (missing || !schema) return
    onSubmit({ schemaId: schema.id, label: schema.label, values })
  }

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/30 px-4 py-6">
      <form onSubmit={handleSubmit} className="w-full max-w-2xl overflow-hidden rounded-2xl border border-line bg-white shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b border-line bg-blue-50/70 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-ink">{title}</h2>
            <p className="mt-1 text-xs text-muted">Fields are type-specific. Required and optional inputs are marked explicitly.</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg px-2 py-1 text-xl leading-none text-muted hover:bg-white">
            ×
          </button>
        </div>
        <div className="max-h-[70vh] space-y-4 overflow-y-auto p-5">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-slate-600">Connector type</span>
            <select
              value={schemaId}
              onChange={(event) => {
                setSchemaId(event.target.value)
                setValues({})
              }}
              className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
            >
              {schemas.map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </select>
            {schema?.description && <span className="block text-xs text-muted">{schema.description}</span>}
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            {activeFields.map((field) => (
              <label key={field.name} className={field.type === 'textarea' ? 'space-y-1 sm:col-span-2' : 'space-y-1'}>
                <span className="flex items-center gap-2 text-xs font-medium text-slate-600">
                  {field.label}
                  <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${field.required ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-500'}`}>
                    {field.required ? 'Required' : 'Optional'}
                  </span>
                </span>
                {field.type === 'select' ? (
                  <select
                    value={values[field.name] ?? field.options?.[0]?.value ?? ''}
                    required={field.required}
                    onChange={(event) => setValue(field.name, event.target.value)}
                    className="w-full rounded-lg border border-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                  >
                    {field.options?.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                ) : field.type === 'textarea' ? (
                  <textarea
                    value={values[field.name] ?? ''}
                    required={field.required}
                    placeholder={field.placeholder}
                    onChange={(event) => setValue(field.name, event.target.value)}
                    className="min-h-24 w-full rounded-lg border border-line px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                  />
                ) : (
                  <input
                    type={field.type ?? 'text'}
                    value={values[field.name] ?? ''}
                    required={field.required}
                    placeholder={field.placeholder}
                    onChange={(event) => setValue(field.name, event.target.value)}
                    className="w-full rounded-lg border border-line px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                  />
                )}
                {field.hint && <span className="block text-xs text-muted">{field.hint}</span>}
              </label>
            ))}
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-line bg-slate-50 px-5 py-4">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit">{submitLabel}</Button>
        </div>
      </form>
    </div>
  )
}
