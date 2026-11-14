import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { useSession } from '../../../shared/auth/useSession'
import { PageHeader } from '../../../shared/ui/PageHeader'
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
    <div className="space-y-4">
      <PageHeader back={{ to: '/orders', label: t('nav.orders') }} title={t('orders.new')} />
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
