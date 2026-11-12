import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router'
import { useSession } from '../shared/auth/useSession'
import { Menu } from '../shared/ui/icons'
import { flattenNav, visibleNav } from './nav'

/** Разделы, вынесенные на нижнюю панель телефона (по порядку, только доступные сессии). */
const PRIMARY = ['dashboard', 'orders', 'trips', 'finance', 'clients']

/** Нижняя навигация для телефона: четыре главных раздела и кнопка «Меню» с остальными. */
export function MobileTabBar({ onMenu }: { onMenu: () => void }) {
  const { t } = useTranslation()
  const { session } = useSession()
  const shown = session ? flattenNav(visibleNav(session)) : []
  const tabs = PRIMARY.map((key) => shown.find((i) => i.key === key && i.path !== undefined)).filter((i) => i !== undefined).slice(0, 4)
  return (
    <nav
      aria-label={t('nav.mobileLabel')}
      className="fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      {tabs.map((item) => {
        const Icon = item.icon
        return (
          <NavLink
            key={item.key}
            to={item.path ?? '/'}
            end={item.path === '/'}
            className={({ isActive }) =>
              `flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 px-1 text-[11px] ${isActive ? 'font-medium text-brand-700 dark:text-brand-200' : 'text-muted'}`
            }
          >
            {Icon ? <Icon className="size-5" aria-hidden="true" /> : null}
            <span className="max-w-full truncate">{t(item.labelKey)}</span>
          </NavLink>
        )
      })}
      <button
        type="button"
        onClick={onMenu}
        className="flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 px-1 text-[11px] text-muted"
      >
        <Menu className="size-5" aria-hidden="true" />
        <span>{t('nav.menu')}</span>
      </button>
    </nav>
  )
}
