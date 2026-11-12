import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createParty, deleteParty, getParty, listParties, updateParty } from './api'
import type { PartyKind, PartyListParams, PartyPayload } from './types'

/** Ключ включает ВСЕ параметры списка: смена любого фильтра - новый запрос (старый отменяется). */
export function usePartyList(kind: PartyKind, params: PartyListParams) {
  return useQuery({
    queryKey: [kind, 'list', params],
    queryFn: ({ signal }) => listParties(kind, params, signal),
    placeholderData: keepPreviousData,
  })
}

function useInvalidate(kind: PartyKind) {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: [kind] }),
      qc.invalidateQueries({ queryKey: ['dashboard'] }), // счётчики клиентов/перевозчиков
    ])
}

export function useSaveParty(kind: PartyKind) {
  const invalidate = useInvalidate(kind)
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: PartyPayload }) =>
      id === null ? createParty(kind, body) : updateParty(kind, id, body),
    onSuccess: invalidate,
  })
}

export function useDeleteParty(kind: PartyKind) {
  const invalidate = useInvalidate(kind)
  return useMutation({ mutationFn: (id: number) => deleteParty(kind, id), onSuccess: invalidate })
}

/** Карточка клиента/перевозчика по id; id=null - запрос не отправляется. */
export function useParty(kind: PartyKind, id: number | null) {
  return useQuery({
    queryKey: [kind, 'detail', id],
    queryFn: ({ signal }) => getParty(kind, id ?? 0, signal),
    enabled: id !== null,
  })
}
