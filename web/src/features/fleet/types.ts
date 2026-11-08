export type VehicleKind = 'tractor' | 'trailer' | 'truck' | 'other'
export type VehicleStatus = 'active' | 'repair' | 'inactive'
export const VEHICLE_KINDS: readonly VehicleKind[] = ['tractor', 'trailer', 'truck', 'other']
export const VEHICLE_STATUSES: readonly VehicleStatus[] = ['active', 'repair', 'inactive']

export interface Vehicle {
  id: number
  kind: VehicleKind
  plate: string
  vin: string
  make: string
  model: string
  year: number | null
  body_type: string
  capacity_kg: number | null
  volume_m3: string | null
  status: VehicleStatus
  gps_check: boolean
  notes: string
}

export type VehiclePayload = Partial<Omit<Vehicle, 'id'>>

export interface VehicleListParams {
  q: string
  kind: '' | VehicleKind
  status: '' | VehicleStatus
  ordering: string
  page: number
  pageSize: number
}

export interface Reminder {
  type: 'service' | 'document' | 'insurance'
  state: 'overdue' | 'due_soon'
  vehicle: number
  plate: string
  title: string
  due_date: string | null
  due_km: number | null
  current_km: number | null
}

export interface MileageCheck {
  enabled: boolean
  official_km?: number | null
  gps_km?: number | null
  gps_available?: boolean
  difference_km?: number | null
  threshold_km?: number
  warning?: boolean
}

export interface OfficialMileage {
  id: number
  trip: number | null
  recorded_at: string
  odometer_km: number
  source: 'trip_start' | 'trip_end' | 'manual'
}

export interface FuelStats {
  average_l_per_100km: string | null
  distance_km: number
}
