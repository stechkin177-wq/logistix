export type DriverAction = 'start' | 'unloading' | 'complete'
export type DriverScope = 'current' | 'upcoming' | 'history'
export const DRIVER_SCOPES: DriverScope[] = ['current', 'upcoming', 'history']

export interface DriverTrip {
  id: number
  number: string
  status: { id: number; code: string; name: string }
  vehicle_plate: string
  trailer_plate: string
  from_city: string
  to_city: string
  starts_at: string | null
  actions: DriverAction[]
  odometer_required: boolean
}

export interface DriverStop {
  id: number
  kind: string
  status: string
  city: string
  street: string
  contact: string
  note: string
  window_from: string
  window_to: string | null
  consignment: string
}

export interface DriverTripDetail extends DriverTrip {
  stops: DriverStop[]
  consignments: { name: string; weight_kg: string | null }[]
}

export interface DriverMe {
  driver: { id: number; full_name: string; phone: string; license_number: string; license_categories: string; license_expires: string | null }
  company: { id: number; name: string; language: string }
}
