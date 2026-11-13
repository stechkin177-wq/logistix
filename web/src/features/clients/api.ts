import { searchParties } from '../parties/api'

export const searchClients = (q: string, signal: AbortSignal) => searchParties('clients', q, signal)

/** Только активные клиенты: для нового заказа (неактивным новые заказы не создаются). */
export const searchActiveClients = (q: string, signal: AbortSignal) => searchParties('clients', q, signal, 'active')
