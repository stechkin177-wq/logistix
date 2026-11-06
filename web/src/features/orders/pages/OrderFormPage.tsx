import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { useSession } from '../../../shared/auth/useSession'
import { ForbiddenPage } from '../../errors/ForbiddenPage'
import { OrderForm } from '../components/OrderForm'
import { useCreateOrder } from '../hooks'

/** /orders/new: форма «Новый заказ» (Контакты, Ценник, Груз, Маршрут). */
export function OrderFormPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { hasPermission } = useSession()
  const create = useCreateOrder()
  if (!hasPermission('orders.create')) return <ForbiddenPage />
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Link to="/orders" className="text-sm text-brand-700 hover:underline dark:text-brand-300">
          ← {t('nav.orders')}
        </Link>
        <h1 className="text-base font-semibold">{t('orders.new')}</h1>
      </div>
      <OrderForm
        mode="create"
        order={null}
        submitting={create.isPending}
        error={create.error}
        onSubmit={(body) => {
          create.mutate(body, { onSuccess: (order) => void navigate(`/orders/${String(order.id)}`) })
        }}
        onCancel={() => void navigate('/orders')}
      />
    </div>
  )
}
