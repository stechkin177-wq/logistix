import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router'
import { useSession } from '../../shared/auth/useSession'
import { Toaster } from '../../shared/ui/Toaster'
import { Camera, Route, UserRound } from '../../shared/ui/icons'
import { useDriverPwa } from './pwa'

const TABS = [
  { to: '/driver', end: true, icon: Route, key: 'trips', module: null },
  { to: '/driver/report', end: false, icon: Camera, key: 'report', module: 'ocr' },
  { to: '/driver/profile', end: false, icon: UserRound, key: 'profile', module: null },
] as const

/** Оболочка водителя: название компании сверху, содержимое, нижняя панель с крупными вкладками. */
export function DriverLayout() {
  const { t } = useTranslation()
  const { session } = useSession()
  useDriverPwa()
  return (
    <div className="fixed inset-0 flex flex-col overscroll-none bg-canvas text-ink">
      <header className="flex h-12 shrink-0 items-center border-b border-line bg-surface px-4 pt-[env(safe-area-inset-top)]">
        <span className="truncate text-sm font-semibold">{session?.company.name ?? 'Logistix'}</span>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto p-3">
        <Outlet />
      </main>
      <nav aria-label={t('driver.navLabel')} className="flex shrink-0 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)]">
        {TABS.filter((tab) => tab.module === null || session?.modules.includes(tab.module)).map(({ to, end, icon: Icon, key }) => (
          <NavLink
            key={key}
            to={to}
            end={end}
            className={({ isActive }) => `flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-xs ${isActive ? 'font-medium text-brand-700 dark:text-brand-200' : 'text-muted'}`}
          >
            <Icon className="size-6" aria-hidden="true" />
            <span>{t(`driver.tabs.${key}`)}</span>
          </NavLink>
        ))}
      </nav>
      <Toaster />
    </div>
  )
}
