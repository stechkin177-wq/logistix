import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { pushToast } from '../../../shared/ui/toast'
import { useCreateTrip } from '../../trips/hooks'
import type { Order } from '../types'

/**
 * «Создать рейс» одной кнопкой из карточки заказа: тот же вызов POST /trips/, что и на странице рейсов
 * (вся логика и проверки - на сервере). Рейс создаётся со всеми грузами заказа без перевозчика и
 * машины; перевозчика, машину и водителя вносят в карточке рейса, куда ведёт переход.
 */
export function CreateTripButton({ order }: { order: Order }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { hasPermission, hasModule } = useSession()
  const create = useCreateTrip()
  if (!hasModule('logistics') || !hasPermission('trips.create')) return null
  const ids = order.consignments.map((c) => c.id)
  return (
    <WriteButton
      variant="primary"
      permission="trips.create"
      disabled={ids.length === 0 || create.isPending}
      title={ids.length === 0 ? t('orders.createTripNoCargo') : undefined}
      onClick={() => {
        create.mutate(
          { consignments: ids, carrier: null, vehicle_plate: '', driver_name: '', carrier_price: '0' },
          {
            onSuccess: (trip) => void navigate(`/trips?open=${String(trip.id)}`),
            onError: (e) => { pushToast('error', errorMessage(e, t)) },
          },
        )
      }}
    >
      {create.isPending ? t('common.saving') : t('orders.createTrip')}
    </WriteButton>
  )
}
