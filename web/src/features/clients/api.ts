import { searchParties } from '../parties/api'

export const searchClients = (q: string, signal: AbortSignal) => searchParties('clients', q, signal)
