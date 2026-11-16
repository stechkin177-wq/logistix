import { useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useIsMobile } from '../hooks/useIsMobile'
import { HeaderSlotContext } from './headerBleed'

/**
 * На телефоне переносит блок (вкладки, подразделы) в неподвижную область под шапкой страницы:
 * при прокрутке списка он остаётся на месте. На компьютере и без области шапки рисуется на месте.
 */
export function MobilePinned({ children }: { children: ReactNode }) {
  const mobile = useIsMobile()
  const slot = useContext(HeaderSlotContext)
  if (!mobile || slot === undefined) return <>{children}</>
  return slot ? createPortal(<div className="order-2 mt-2">{children}</div>, slot) : null
}
