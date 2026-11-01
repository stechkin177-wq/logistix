import { useDeleteParty, usePartyList, useSaveParty } from '../parties/hooks'
import type { PartyListParams } from '../parties/types'

export const useClientList = (params: PartyListParams) => usePartyList('clients', params)
export const useSaveClient = () => useSaveParty('clients')
export const useDeleteClient = () => useDeleteParty('clients')
