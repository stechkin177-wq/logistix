import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, useLocation } from 'react-router'
import { useBranding } from '../shared/branding/useBranding'
import { useSession } from '../shared/auth/useSession'
import { ChevronDown } from '../shared/ui/icons'
import { visibleNav, type NavItem } from './nav'

const LINK = 'flex items-center gap-2.5 rounded-control px-3 py-2 text-sm transition-colors'
const ACTIVE = 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-900/50 dark:text-brand-100'
const IDLE = 'text-muted hover:bg-surface-2 hover:text-ink'

function NavEntry({ item, child = false }: { item: NavItem; child?: boolean }) {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const [manual, setManual] = useState<boolean | null>(null)
  const Icon = item.icon
  const iconCls = child ? 'size-4' : 'size-[18px]'
  // Группа настроек - одна строка меню: подразделы открываются слева на самой странице настроек
  const isSettingsHub = item.path === undefined && item.key === 'settings'
  const to = isSettingsHub ? '/settings' : item.path
  if (to === undefined) return null
  const hubActive = isSettingsHub && pathname.startsWith('/settings')
  // «Данные и документы» - раскрывающийся список под «Настройки»; сам открывается, когда в нём работаем
  const dataItems = isSettingsHub ? (item.children ?? []).filter((c) => c.section === 'data') : []
  const inData = dataItems.some((c) => c.path !== undefined && pathname.startsWith(c.path))
  const expanded = manual ?? inData
  return (
    <li className={child ? 'relative before:absolute before:-left-2 before:top-1/2 before:h-px before:w-2 before:bg-line' : 'relative'}>
      <NavLink
        to={to}
        end={to === '/'}
        className={({ isActive }) => `${LINK} ${child ? 'py-1.5 pl-2.5' : ''} ${isActive || hubActive ? ACTIVE : IDLE}`}
      >
        {Icon ? <Icon className={`${iconCls} shrink-0`} aria-hidden="true" /> : null}
        <span className="truncate">{t(item.labelKey)}</span>
      </NavLink>
      {dataItems.length > 0 ? (
        <>
          <button
            type="button"
            aria-expanded={expanded}
            aria-label={t('nav.sectionData')}
            title={t('nav.sectionData')}
            onClick={() => { setManual(!expanded) }}
            className="absolute right-1.5 top-1.5 inline-flex size-6 items-center justify-center rounded text-muted hover:bg-surface-2 hover:text-ink"
          >
            <ChevronDown className={`size-4 transition-transform ${expanded ? 'rotate-180' : ''}`} aria-hidden="true" />
          </button>
          {expanded ? (
            <>
              <p className="ml-[1.375rem] mt-1 pl-2 text-[10px] font-semibold uppercase tracking-wide text-muted">{t('nav.sectionData')}</p>
              <ul className="mb-1 ml-[1.375rem] mt-0.5 space-y-0.5 border-l border-line pl-2">
                {dataItems.map((c) => <NavEntry key={c.key} item={c} child />)}
              </ul>
            </>
          ) : null}
        </>
      ) : null}
      {!isSettingsHub && item.children ? (
        <ul className="mb-1 ml-[1.375rem] mt-0.5 space-y-0.5 border-l border-line pl-2">
          {item.children.map((c) => (
            <NavEntry key={c.key} item={c} child />
          ))}
        </ul>
      ) : null}
    </li>
  )
}

/** Боковое меню: плавающая панель на компьютере, полноэкранная шторка на телефоне. */
export function Sidebar({ onNavigate, flat = false }: { onNavigate?: () => void; flat?: boolean }) {
  const { t } = useTranslation()
  const { session } = useSession()
  const branding = useBranding()
  const items = session ? visibleNav(session) : []

  return (
    <aside
      className={`flex h-full shrink-0 flex-col bg-surface ${flat ? 'w-full' : 'w-60 rounded-card border border-line shadow-card'}`}
    >
      <div className="flex h-14 items-center gap-2.5 px-4">
        {branding.logo_url ? (
          <img src={branding.logo_url} alt="" className="size-7 rounded-md object-contain" />
        ) : (
          <span aria-hidden="true" className="inline-flex size-7 items-center justify-center rounded-md bg-brand-600 text-xs font-bold text-brand-fg">
            {branding.app_name.charAt(0).toUpperCase()}
          </span>
        )}
        <span className="truncate text-sm font-semibold">{branding.app_name}</span>
      </div>
      <nav aria-label={t('nav.label')} className="thin-scroll min-h-0 flex-1 overflow-y-auto px-2 pb-2" onClick={onNavigate}>
        <ul className="space-y-0.5">
          {items.map((item) => (
            <NavEntry key={item.key} item={item} />
          ))}
        </ul>
      </nav>
    </aside>
  )
}
