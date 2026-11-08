import { useTranslation } from 'react-i18next'
import { Badge, type Tone } from '../../../shared/ui/Badge'
import type { LocationStatus } from '../types'

const TONES: Record<LocationStatus, Tone> = {
  planned: 'neutral', in_transit: 'info', at_stop: 'warning', in_storage: 'warning', delivered: 'success',
}

/** Бейдж местонахождения груза (location_status). */
export function LocationBadge({ status }: { status: LocationStatus | undefined }) {
  const { t } = useTranslation()
  if (!status) return null
  return <Badge tone={TONES[status]}>{t(`tracking.location.${status}`)}</Badge>
}
