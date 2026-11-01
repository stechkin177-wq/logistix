import { searchParties } from '../parties/api'

export const searchCarriers = (q: string, signal: AbortSignal) => searchParties('carriers', q, signal)
