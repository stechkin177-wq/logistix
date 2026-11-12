import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Outlet } from 'react-router'
import { useSession } from '../shared/auth/useSession'
import { useBranding } from '../shared/branding/useBranding'
import { Toaster } from '../shared/ui/Toaster'
import { LimitBanner } from './LimitBanner'
import { MobileTabBar } from './MobileTabBar'
import { ReadonlyBanner } from './ReadonlyBanner'
import { Sidebar } from './Sidebar'

export function AppLayout() {
  const { t } = useTranslation()
  const { session } = useSession()
  const branding = useBranding()
  const [open, setOpen] = useState(false)

  return (
    <div className="flex h-dvh bg-canvas text-ink">
      <div className="hidden p-3 pr-0 md:block">
        <Sidebar />
      </div>
      {open ? (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="w-72 max-w-[85vw] bg-surface shadow-pop">
            <Sidebar
              flat
              onNavigate={() => {
                setOpen(false)
              }}
            />
          </div>
          <button
            type="button"
            aria-label={t('common.close')}
            className="flex-1 bg-slate-950/50"
            onClick={() => {
              setOpen(false)
            }}
          />
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-surface px-3 md:hidden">
          <span className="truncate text-sm font-semibold">{branding.app_name}</span>
          <span className="ml-auto truncate text-xs text-muted">{session?.company.name}</span>
        </header>
        <ReadonlyBanner />
        <LimitBanner />
        <main className="thin-scroll min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-3 pb-20 md:p-5 md:pb-5">
          <div className="mx-auto w-full max-w-[1500px]">
            {/* key: при смене компании страницы монтируются заново и не держат чужие данные */}
            <Outlet key={session?.company.id} />
          </div>
        </main>
      </div>
      <MobileTabBar onMenu={() => { setOpen(true) }} />
      <Toaster />
    </div>
  )
}
