import { useTranslation } from 'react-i18next'
import { Link, matchPath, useLocation } from 'react-router'
import { useSession } from '../shared/auth/useSession'
import { ChevronRight, UserRound } from '../shared/ui/icons'
import { ThemeToggle } from '../shared/ui/ThemeToggle'
import { LanguageSwitch } from '../shared/ui/LanguageSwitch'
import { flattenNav, visibleNav, type NavItem } from './nav'
import { ProfileMenu } from './ProfileMenu'

/** Раздел меню, которому принадлежит адрес: самый длинный совпавший путь (карточки заказов и рейсов - в своём разделе). */
export function currentSection(pathname: string, items: NavItem[]): NavItem | undefined {
  const flat = flattenNav(items).filter((i): i is NavItem & { path: string } => i.path !== undefined)
  const match = flat
    .filter((i) => (i.path === '/' ? pathname === '/' : matchPath({ path: i.path, end: false }, pathname) !== null))
    .sort((a, b) => b.path.length - a.path.length)[0]
  if (match) return match
  // страницы настроек без своего пункта (/settings) - сам раздел «Настройки»
  return items.find((i) => i.key === 'settings' && pathname.startsWith('/settings'))
}

/**
 * Верхняя полоса: слева выделенное название текущего раздела (не прокручивается вместе со страницей),
 * справа - переключатель языка и аккаунт с кнопкой «Выйти».
 */
export function TopBar() {
  const { t } = useTranslation()
  const { session } = useSession()
  const { pathname } = useLocation()
  const items = session ? visibleNav(session) : []
  const section = currentSection(pathname, items)
  const parent = section ? items.find((i) => i.children?.some((c) => c.key === section.key)) : undefined
  // организационные и финансовые страницы настроек - это «Профиль»
  const inProfile = section?.section === 'organization' || section?.section === 'finance'
  const Icon = inProfile ? UserRound : (parent ?? section)?.icon
  return (
    <header className="flex h-12 shrink-0 touch-none select-none items-center gap-3 border-b border-line bg-surface px-3 md:h-auto md:border-b-0 md:bg-transparent md:px-5 md:pb-0 md:pt-3">
      {section ? (
        <p className="flex min-w-0 items-center gap-1.5 rounded-control bg-brand-50 px-3 py-1.5 text-sm font-semibold text-brand-700 dark:bg-brand-900/50 dark:text-brand-100">
          {Icon ? <Icon className="size-4 shrink-0" aria-hidden="true" /> : null}
          {parent ? (
            <>
              <Link to={parent.path ?? (inProfile ? '/settings/company' : '/settings')} className="shrink-0 hover:underline">
                {inProfile ? t('nav.profileTitle') : t(parent.labelKey)}
              </Link>
              <ChevronRight className="size-3.5 shrink-0 opacity-60" aria-hidden="true" />
            </>
          ) : null}
          {section.path !== undefined && pathname !== section.path ? (
            <Link to={section.path} className="truncate hover:underline">{t(section.labelKey)}</Link>
          ) : (
            <span className="truncate">{t(section.labelKey)}</span>
          )}
        </p>
      ) : null}
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <LanguageSwitch />
        <ThemeToggle />
        <ProfileMenu />
      </div>
    </header>
  )
}
