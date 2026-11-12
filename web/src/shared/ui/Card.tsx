import type { HTMLAttributes, ReactNode } from 'react'

/** Белая панель со скруглением и мягкой тенью: основа всех блоков страницы. */
export function Card({ className = '', children, ...rest }: HTMLAttributes<HTMLElement> & { children: ReactNode }) {
  return (
    <section
      className={`rounded-card border border-line bg-surface shadow-card ${className}`}
      {...rest}
    >
      {children}
    </section>
  )
}

/** Заголовок блока внутри Card: название слева, действия справа. */
export function CardHeader({ title, actions, hint }: { title: ReactNode; actions?: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {hint ? <p className="mt-0.5 text-xs text-muted">{hint}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

/** Тело блока с единым внутренним отступом. */
export function CardBody({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`p-4 ${className}`}>{children}</div>
}
