import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
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
    <div className="pointer-events-none fixed right-3 top-3 z-50 flex w-80 flex-col gap-2">
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <Banner kind={toast.kind}>{toast.message}</Banner>
        </div>
      ))}
    </div>
  )
}
