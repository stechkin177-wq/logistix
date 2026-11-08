import { useTranslation } from 'react-i18next'
import { Badge, type Tone } from '../../../shared/ui/Badge'
import type { CargoTransfer } from '../types'

const TONES: Record<string, Tone> = { initiated: 'warning', confirmed: 'success', reversed: 'danger' }

/** Статус передачи; подтверждённая, но отменённая сторно, показывается как «Отменена сторно». */
export function TransferStatusBadge({ transfer }: { transfer: CargoTransfer }) {
  const { t } = useTranslation()
  const key = transfer.reversed_by !== null ? 'cancelled' : transfer.status
  return <Badge tone={key === 'cancelled' ? 'neutral' : TONES[key]}>{t(`tracking.transferStatus.${key}`)}</Badge>
}
