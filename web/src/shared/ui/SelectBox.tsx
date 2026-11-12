import type { ReactNode } from 'react'
import { ChevronDown } from './icons'

/** Обёртка нативного <select> с единой стрелкой; сам select остаётся нативным (клавиатура, мобильный выбор). */
export function SelectBox({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`relative ${className}`}>
      {children}
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden="true" />
    </div>
  )
}
