export function Spinner({ label }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-muted">
      <span className="size-4 animate-spin rounded-full border-2 border-line border-t-brand-600" />
      {label ? <span>{label}</span> : null}
    </span>
  )
}
