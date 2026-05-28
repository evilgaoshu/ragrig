interface Props {
  title: string
  description?: string
  legacyAnchor?: string
}

export default function Stub({ title, description, legacyAnchor }: Props) {
  const fallbackPath = legacyAnchor ? `/${legacyAnchor}` : '/'

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-gray-900">{title}</h1>
        {description && <p className="text-gray-500 text-sm mt-0.5">{description}</p>}
      </div>
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-700">
        This React page is still being filled in.{' '}
        <a href={fallbackPath} className="underline font-medium">
          Return to the app
        </a>
        .
      </div>
    </div>
  )
}
