import { useState } from 'react'
import { HeaderSlotContext, HintSlotContext } from '../shared/ui/headerBleed'
import { useTranslation } from 'react-i18next'
import { Outlet } from 'react-router'
import { useSession } from '../shared/auth/useSession'
import { Toaster } from '../shared/ui/Toaster'
import { LimitDialog } from './LimitBanner'
import { MobileTabBar } from './MobileTabBar'
import { ReadonlyBanner } from './ReadonlyBanner'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'

export function AppLayout() {
  const { t } = useTranslation()
  const { session } = useSession()
  const [open, setOpen] = useState(false)
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  const [hintSlot, setHintSlot] = useState<HTMLElement | null>(null)

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
        <TopBar />
        {/* шапка страницы живёт здесь, вне прокрутки: основной экран начинается строго под ней */}
        <div className="thin-scroll shrink-0 overflow-y-hidden [scrollbar-gutter:stable] empty:hidden">
          <div ref={setSlot} className="mx-auto flex w-full max-w-[1500px] flex-col px-3 pt-3 empty:hidden md:px-5 md:pt-2" />
        </div>
        <main className="thin-scroll min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto [scrollbar-gutter:stable] p-3 pb-20 pt-0 md:p-5 md:pb-5 md:pt-0">
          <div className="mx-auto w-full max-w-[1500px] space-y-3 pt-3">
            <div ref={setHintSlot} className="empty:hidden" />
            {/* предупреждения - в колонке страницы, ровно по её краям */}
            <div className="space-y-3 pt-3 empty:hidden">
              <ReadonlyBanner />
            </div>
            {/* key: при смене компании страницы монтируются заново и не держат чужие данные */}
            <HeaderSlotContext.Provider value={slot}>
              <HintSlotContext.Provider value={hintSlot}>
                <Outlet key={session?.company.id} />
              </HintSlotContext.Provider>
            </HeaderSlotContext.Provider>
          </div>
        </main>
      </div>
      <MobileTabBar onMenu={() => { setOpen(true) }} />
      <LimitDialog />
      <Toaster />
    </div>
  )
}
