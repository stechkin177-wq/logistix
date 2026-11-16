import { createContext } from 'react'

/**
 * Место под шапку страницы вне прокручиваемой области (создаёт AppLayout).
 * undefined - слота нет, шапка рисуется на месте; null - слот ещё не смонтирован.
 */
export const HeaderSlotContext = createContext<HTMLElement | null | undefined>(undefined)
