import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  confirmTransfer, createEvent, createTransfer, listConsignmentTransfers, listEvents, listTransfers, reverseTransfer,
} from './api'
import type { EventType, TransferListParams, TransferPayload } from './types'

export function useEvents(consignment: number, enabled = true) {
  return useQuery({ queryKey: ['tracking', 'events', consignment], queryFn: ({ signal }) => listEvents(consignment, signal), enabled })
}

export function useConsignmentTransfers(consignment: number, enabled = true) {
  return useQuery({
    queryKey: ['tracking', 'transfers', consignment],
    queryFn: ({ signal }) => listConsignmentTransfers(consignment, signal),
    enabled,
  })
}

export function useTransferList(params: TransferListParams) {
  return useQuery({
    queryKey: ['tracking', 'transfer-list', params],
    queryFn: ({ signal }) => listTransfers(params, signal),
    placeholderData: keepPreviousData,
  })
}

/** Передачи и события меняют местонахождение груза: обновляем грузы и заказы. */
function useInvalidateTracking() {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['tracking'] }),
      qc.invalidateQueries({ queryKey: ['consignments'] }),
      qc.invalidateQueries({ queryKey: ['orders'] }),
    ])
}

export function useCreateEvent(consignment: number) {
  const invalidate = useInvalidateTracking()
  return useMutation({
    mutationFn: (body: { event_type: EventType; stop: number; note?: string }) => createEvent(consignment, body),
    onSuccess: invalidate,
  })
}

export function useCreateTransfer(consignment: number) {
  const invalidate = useInvalidateTracking()
  return useMutation({ mutationFn: (body: TransferPayload) => createTransfer(consignment, body), onSuccess: invalidate })
}

export function useConfirmTransfer() {
  const invalidate = useInvalidateTracking()
  return useMutation({ mutationFn: (id: number) => confirmTransfer(id), onSuccess: invalidate })
}

export function useReverseTransfer() {
  const invalidate = useInvalidateTracking()
  return useMutation({ mutationFn: ({ id, note }: { id: number; note?: string }) => reverseTransfer(id, note), onSuccess: invalidate })
}
