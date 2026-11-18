import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { PageHeader } from '../../shared/ui/PageHeader'
import { Tabs } from '../../shared/ui/Tabs'
import { History, Map, MapPin, Settings, Shield, type LucideIcon } from '../../shared/ui/icons'
import { useSession } from '../../shared/auth/useSession'
import { EventsTab } from './EventsTab'
import { GeofencesTab } from './GeofencesTab'
import { MapTab } from './MapTab'
import { UnitsTab } from './UnitsTab'

const TAB_KEYS = ['map', 'units', 'geofences', 'events'] as const
const TAB_ICONS: Record<(typeof TAB_KEYS)[number], LucideIcon> = { map: Map, units: MapPin, geofences: Shield, events: History }
const SCHEMA = { tab: codecs.oneOf(TAB_KEYS, 'map') }

/** GPS-мониторинг: техника из Wialon с привязкой к технике парка, геозоны и события въезда/выезда. */
export function GpsPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA)
  const { hasPermission } = useSession()
  return (
    <div className="space-y-3">
      <PageHeader
        icon={MapPin}
        title={t('nav.gps')}
        actions={
          hasPermission('gps.manage') ? (
            <Link to="/settings/gps" className="inline-flex h-9 items-center gap-2 rounded-control border border-line bg-surface px-3 text-sm font-medium hover:bg-surface-2">
              <Settings className="size-4" aria-hidden="true" />
              {t('gps.settingsLink')}
            </Link>
          ) : undefined
        }
      />
      <Tabs
        label={t('gps.tabsLabel')}
        active={state.tab}
        variant="pills"
        pinned
        tabs={TAB_KEYS.map((key) => ({ key, icon: TAB_ICONS[key], label: t(`gps.tabs.${key}`) }))}
        onChange={(tab) => { setState({ tab: TAB_KEYS.find((k) => k === tab) ?? 'map' }) }}
      />
      <div role="tabpanel" id={`panel-${state.tab}`} aria-labelledby={`tab-${state.tab}`}>
        {state.tab === 'map' ? <MapTab /> : state.tab === 'units' ? <UnitsTab /> : state.tab === 'geofences' ? <GeofencesTab /> : <EventsTab />}
      </div>
    </div>
  )
}
