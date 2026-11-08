export type DriverStatus = 'active' | 'on_leave' | 'inactive'
export const DRIVER_STATUSES: readonly DriverStatus[] = ['active', 'on_leave', 'inactive']

export interface DriverDocument {
  id: number
  driver: number
  kind: 'license' | 'passport' | 'medical' | 'other'
  number: string
  issued_at: string | null
  expires_at: string | null
  notes: string
}

export interface Driver {
  id: number
  full_name: string
  phone: string
  iin: string
  birth_date: string | null
  license_number: string
  license_categories: string
  license_expires: string | null
  status: DriverStatus
  user: number | null
  notes: string
  documents: DriverDocument[]
  created_at: string
  updated_at: string
}

export type DriverPayload = Partial<Omit<Driver, 'id' | 'documents' | 'created_at' | 'updated_at'>>

export interface DriverListParams {
  q: string
  status: '' | DriverStatus
  ordering: string
  page: number
  pageSize: number
}
