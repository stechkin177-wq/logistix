import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { useSession } from '../../../shared/auth/useSession'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { Plus } from '../../../shared/ui/icons'

/** «Новый заказ»: ссылка при праве записи; в режиме только чтения - отключённая кнопка с пояснением; без права - ничего. */
export function NewOrderLink() {
  const { t } = useTranslation()
  const canWrite = useCanWrite('orders.create')
  const { hasPermission } = useSession()
  if (canWrite) {
    return (
      <Link to="/orders/new" className="inline-flex h-9 items-center justify-center gap-1.5 whitespace-nowrap rounded-control bg-brand-600 px-3.5 text-sm font-medium text-brand-fg shadow-sm transition-colors hover:bg-brand-solid-hover">
        <Plus className="size-4 shrink-0" aria-hidden="true" />
        {t('orders.new')}
      </Link>
    )
  }
  return hasPermission('orders.create') ? (
    <WriteButton variant="primary" icon={Plus} permission="orders.create">{t('orders.new')}</WriteButton>
  ) : null
}
