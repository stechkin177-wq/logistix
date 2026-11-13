import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createAccount, createContract, deleteAccount, deleteContract, listAccounts, listContracts, updateAccount, updateContract,
} from './api'
import type { BankAccountPayload, ContractPayload, PartyOwner } from './types'

export function useContracts(owner: PartyOwner | null, enabled = true) {
  return useQuery({
    queryKey: ['contracts', owner],
    queryFn: ({ signal }) => listContracts(owner as PartyOwner, signal),
    enabled: enabled && owner !== null,
  })
}

/** Договоры меняют и карточку стороны (счётчики), и выбор в заказах/рейсах. */
function useInvalidateContracts() {
  const qc = useQueryClient()
  return () => Promise.all([qc.invalidateQueries({ queryKey: ['contracts'] }), qc.invalidateQueries({ queryKey: ['orders'] }), qc.invalidateQueries({ queryKey: ['trips'] })])
}

export function useSaveContract() {
  const invalidate = useInvalidateContracts()
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: ContractPayload }) => (id === null ? createContract(body) : updateContract(id, body)),
    onSuccess: invalidate,
  })
}

export function useDeleteContract() {
  const invalidate = useInvalidateContracts()
  return useMutation({ mutationFn: (id: number) => deleteContract(id), onSuccess: invalidate })
}

export function useAccounts(owner: PartyOwner | null) {
  return useQuery({
    queryKey: ['bank-accounts', owner],
    queryFn: ({ signal }) => listAccounts(owner as PartyOwner, signal),
    enabled: owner !== null,
  })
}

/** Счета меняют зеркало bank/iban в карточке стороны: обновляем и её. */
function useInvalidateAccounts(owner: PartyOwner) {
  const qc = useQueryClient()
  return () => Promise.all([qc.invalidateQueries({ queryKey: ['bank-accounts'] }), qc.invalidateQueries({ queryKey: [owner.kind === 'client' ? 'clients' : 'carriers'] })])
}

export function useSaveAccount(owner: PartyOwner) {
  const invalidate = useInvalidateAccounts(owner)
  return useMutation({
    mutationFn: ({ id, body }: { id: number | null; body: BankAccountPayload }) => (id === null ? createAccount(body) : updateAccount(id, body)),
    onSuccess: invalidate,
  })
}

export function useDeleteAccount(owner: PartyOwner) {
  const invalidate = useInvalidateAccounts(owner)
  return useMutation({ mutationFn: (id: number) => deleteAccount(id), onSuccess: invalidate })
}
