import { useDeleteParty, usePartyList, useSaveParty } from '../parties/hooks'
import type { PartyListParams } from '../parties/types'

export const useCarrierList = (params: PartyListParams) => usePartyList('carriers', params)
export const useSaveCarrier = () => useSaveParty('carriers')
export const useDeleteCarrier = () => useDeleteParty('carriers')
