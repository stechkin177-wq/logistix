import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { onApiEvent } from '../api/events'
import { Banner } from './Banner'
import { pushToast, useToasts } from './toast'

/** Контейнер уведомлений; сам показывает отказ сервера «только чтение» (403 subscription_readonly). */
export function Toaster() {
  const { t } = useTranslation()
  const toasts = useToasts()

  useEffect(
    () =>
      onApiEvent('readonly', () => {
        pushToast('warning', t('errors.subscriptionReadonly'))
      }),
    [t],
  )

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed right-3 top-3 z-50 flex w-[calc(100vw-1.5rem)] max-w-80 flex-col gap-2"
    >
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <Banner kind={toast.kind}>
            {toast.message}
            {toast.action ? (
              <>
                {' '}
                <Link to={toast.action.to} className="font-medium underline">
                  {toast.action.label}
                </Link>
              </>
            ) : null}
          </Banner>
        </div>
      ))}
    </div>
  )
}
