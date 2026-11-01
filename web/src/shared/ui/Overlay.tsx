import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

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
    const first = root?.querySelector<HTMLElement>('[data-autofocus], ' + FOCUSABLE)
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
      className={`fixed inset-0 z-40 flex bg-black/40 ${isDrawer ? 'justify-end' : 'items-center justify-center p-3'}`}
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
        className={`flex max-h-full flex-col bg-white shadow-xl outline-none dark:bg-slate-900 ${
          isDrawer ? `h-full w-full ${width ?? 'max-w-xl'}` : `w-full rounded ${width ?? 'max-w-md'}`
        }`}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 dark:border-slate-700">
          <h2 id={titleId} className="text-sm font-semibold">
            {title}
          </h2>
          <button
            type="button"
            aria-label={t('common.close')}
            disabled={busy}
            onClick={onClose}
            className="rounded px-2 text-lg leading-none text-slate-500 hover:bg-slate-100 disabled:opacity-50 dark:hover:bg-slate-800"
          >
            ×
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">{children}</div>
        {footer ? (
          <div className="flex justify-end gap-2 border-t border-slate-200 px-3 py-2 dark:border-slate-700">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}
