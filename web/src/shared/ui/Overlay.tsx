import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { X } from './icons'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export interface OverlayProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  /** Drawer - панель справа, Dialog - по центру. */
  variant?: 'dialog' | 'drawer'
  /** Нельзя закрыть Escape/кликом по фону (идёт сохранение). */
  busy?: boolean
  /** ARIA-роль: alertdialog для подтверждений. */
  role?: 'dialog' | 'alertdialog'
  width?: string
}

/**
 * Доступное модальное окно: role=dialog + aria-modal, Escape закрывает, Tab зациклен внутри,
 * фокус при открытии уходит в окно, при закрытии возвращается на элемент, открывший его.
 */
export function Overlay({
  open, title, onClose, children, footer, variant = 'dialog', busy = false, role = 'dialog', width,
}: OverlayProps) {
  const { t } = useTranslation()
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const returnTo = useRef<Element | null>(null)

  useEffect(() => {
    if (!open) return
    returnTo.current = document.activeElement
    const root = panel.current
    const first = root?.querySelector<HTMLElement>('[data-autofocus]') ?? root?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? root)?.focus()
    return () => {
      const target = returnTo.current
      if (target instanceof HTMLElement && target.isConnected) target.focus()
    }
  }, [open])

  if (!open) return null

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation() // вложенное окно закрывается первым
      if (!busy) onClose()
      return
    }
    if (event.key !== 'Tab' || !panel.current) return
    const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE))
    if (items.length === 0) {
      event.preventDefault()
      return
    }
    const firstItem = items[0]
    const lastItem = items[items.length - 1]
    const active = document.activeElement
    if (event.shiftKey && (active === firstItem || active === panel.current)) {
      event.preventDefault()
      lastItem?.focus()
    } else if (!event.shiftKey && active === lastItem) {
      event.preventDefault()
      firstItem?.focus()
    }
  }

  const isDrawer = variant === 'drawer'
  return createPortal(
    <div
      className={`fixed inset-0 z-40 flex bg-slate-950/50 backdrop-blur-[1px] ${isDrawer ? 'justify-end' : 'items-end justify-center sm:items-center sm:p-3'}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div
        ref={panel}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className={`flex max-h-full flex-col bg-surface text-ink shadow-pop outline-none ${
          isDrawer
            ? `h-full w-full rounded-l-card ${width ?? 'max-w-xl'} max-md:rounded-none`
            : `w-full rounded-t-card sm:rounded-card ${width ?? 'max-w-md'}`
        }`}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 id={titleId} className="text-base font-semibold">
            {title}
          </h2>
          <button
            type="button"
            aria-label={t('common.close')}
            disabled={busy}
            onClick={onClose}
            className="inline-flex size-8 items-center justify-center rounded-control text-muted hover:bg-surface-2 hover:text-ink disabled:opacity-50"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
        <div className="thin-scroll min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
        {footer ? (
          <div className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}
