interface Props {
  title: string
  description?: string
  legacyAnchor?: string
}

export default function Stub({ title, description, legacyAnchor }: Props) {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-gray-900">{title}</h1>
        {description && <p className="text-gray-500 text-sm mt-0.5">{description}</p>}
      </div>
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-700">
        This page is being migrated to React.{' '}
        {legacyAnchor ? (
          <>
            Use the{' '}
            <a href={`/console#${legacyAnchor}`} className="underline font-medium">
              legacy console
            </a>{' '}
            in the meantime.
          </>
        ) : (
          <>
            Use the{' '}
            <a href="/console" className="underline font-medium">
              legacy console
            </a>{' '}
            in the meantime.
          </>
        )}
      </div>
    </div>
  )
}
