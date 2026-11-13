import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { BankAccount, BankAccountPayload, Contract, ContractPayload, PartyOwner } from './types'

const ownerQuery = (owner: PartyOwner) => ({ [owner.kind]: owner.id })

export const listContracts = (owner: PartyOwner, signal?: AbortSignal) =>
  api.get<Paginated<Contract>>('/contracts/', { ...ownerQuery(owner), page_size: 100 }, { signal })

export const createContract = (body: ContractPayload) => api.post<Contract>('/contracts/', body)
export const updateContract = (id: number, body: Partial<ContractPayload>) => api.patch<Contract>(`/contracts/${String(id)}/`, body)
export const deleteContract = (id: number) => api.delete(`/contracts/${String(id)}/`)

export const listAccounts = (owner: PartyOwner, signal?: AbortSignal) =>
  api.get<BankAccount[]>('/bank-accounts/', ownerQuery(owner), { signal })

export const createAccount = (body: BankAccountPayload) => api.post<BankAccount>('/bank-accounts/', body)
export const updateAccount = (id: number, body: Partial<BankAccountPayload>) => api.patch<BankAccount>(`/bank-accounts/${String(id)}/`, body)
export const deleteAccount = (id: number) => api.delete(`/bank-accounts/${String(id)}/`)
