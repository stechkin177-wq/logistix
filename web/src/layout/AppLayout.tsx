import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Outlet } from 'react-router'
import { useSession } from '../shared/auth/useSession'
import { useBranding } from '../shared/branding/useBranding'
import { Button } from '../shared/ui/Button'
import { Toaster } from '../shared/ui/Toaster'
import { ReadonlyBanner } from './ReadonlyBanner'
import { Sidebar } from './Sidebar'

export function AppLayout() {
  const { t } = useTranslation()
  const { session } = useSession()
  const branding = useBranding()
  const [open, setOpen] = useState(false)

  return (
    <div className="flex h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="hidden md:block">
        <Sidebar />
      </div>
      {open ? (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <Sidebar
            onNavigate={() => {
              setOpen(false)
            }}
          />
          <button
            type="button"
            aria-label={t('common.close')}
            className="flex-1 bg-black/40"
            onClick={() => {
              setOpen(false)
            }}
          />
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center gap-2 border-b border-slate-200 bg-white px-3 md:hidden dark:border-slate-800 dark:bg-slate-900">
          <Button
            variant="ghost"
            aria-label={t('nav.menu')}
            onClick={() => {
              setOpen(true)
            }}
          >
            ☰
          </Button>
          <span className="truncate text-sm font-semibold">{branding.app_name}</span>
        </header>
        <ReadonlyBanner />
        <main className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-3 md:p-4">
          {/* key: при смене компании страницы монтируются заново и не держат чужие данные */}
          <Outlet key={session?.company.id} />
        </main>
      </div>
      <Toaster />
    </div>
  )
}
