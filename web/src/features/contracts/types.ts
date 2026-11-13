export type ContractKind = 'main' | 'supplement' | 'other'

export interface Contract {
  id: number
  client: number | null
  carrier: number | null
  party_name: string
  kind: ContractKind
  number: string
  date: string
  valid_until: string | null
  title: string
  comment: string
  source: 'manual' | 'imported'
  is_expired: boolean
  in_use: boolean
  created_at: string
}

export interface ContractPayload {
  client?: number
  carrier?: number
  kind: ContractKind
  number: string
  date: string
  valid_until: string | null
  title: string
  comment: string
}

export interface BankAccount {
  id: number
  client: number | null
  carrier: number | null
  legal_entity: number | null
  bank: string
  bic: string
  iban: string
  kbe: string
  currency: string
  is_default: boolean
  note: string
  created_at: string
}

export type BankAccountPayload = Pick<BankAccount, 'bank' | 'bic' | 'iban' | 'kbe' | 'currency' | 'note'> & {
  client?: number
  carrier?: number
  is_default?: boolean
}

export type PartyOwner = { kind: 'client' | 'carrier'; id: number }
