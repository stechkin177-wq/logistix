import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { useSession } from '../../../shared/auth/useSession'
import { WriteButton } from '../../../shared/ui/WriteButton'

/** «Новый заказ»: ссылка при праве записи; в режиме только чтения - отключённая кнопка с пояснением; без права - ничего. */
export function NewOrderLink() {
  const { t } = useTranslation()
  const canWrite = useCanWrite('orders.create')
  const { hasPermission } = useSession()
  if (canWrite) {
    return (
      <Link to="/orders/new" className="inline-flex h-8 items-center rounded bg-brand-600 px-3 text-sm font-medium text-white hover:bg-brand-700">
        {t('orders.new')}
      </Link>
    )
  }
  return hasPermission('orders.create') ? (
    <WriteButton variant="primary" permission="orders.create">{t('orders.new')}</WriteButton>
  ) : null
}
