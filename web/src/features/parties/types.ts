export type PartyKind = 'clients' | 'carriers'
export type PartyStatus = 'active' | 'inactive'

export interface Contact {
  id: number
  name: string
  position: string
  phone: string
  email: string
}

export interface PartyBase {
  id: number
  name: string
  bin_iin: string
  type: number | null
  type_name: string | null
  status: PartyStatus
  notes: string
  address: string
  bank: string
  iban: string
  contacts: Contact[]
  created_at: string
}

export interface Client extends PartyBase {
  credit_limit: string
  orders_count: number
}

export interface Carrier extends PartyBase {
  rating: string | null
}

export type Party = Client | Carrier

export interface PartyListParams {
  q: string
  type: number | null
  status: '' | PartyStatus
  ordering: string
  page: number
  pageSize: number
}

/** Контакт в теле запроса: id есть у существующих (заменяют набор целиком). */
export interface ContactPayload {
  id?: number
  name: string
  position: string
  phone: string
  email: string
}

export interface PartyPayload {
  name: string
  bin_iin: string
  type: number | null
  status: PartyStatus
  notes: string
  address: string
  bank?: string
  iban?: string
  contacts: ContactPayload[]
  credit_limit?: string
  rating?: string | null
}
