export type LocationStatus = 'planned' | 'in_transit' | 'at_stop' | 'in_storage' | 'delivered'
export type TransferKind = 'to_carrier' | 'between_vehicles' | 'to_storage' | 'from_storage'
export type TransferStatus = 'initiated' | 'confirmed' | 'reversed'
export type EventType = 'arrived' | 'loaded' | 'departed' | 'transferred' | 'unloaded' | 'delivered' | 'skipped' | 'stored'

export const LOCATION_STATUSES: LocationStatus[] = ['planned', 'in_transit', 'at_stop', 'in_storage', 'delivered']
export const TRANSFER_KINDS: TransferKind[] = ['to_carrier', 'between_vehicles', 'to_storage', 'from_storage']

export interface ConsignmentEvent {
  id: number
  consignment: number
  stop: number | null
  stop_seq: number | null
  stop_city: string | null
  leg: number | null
  trip: number | null
  trip_number: string | null
  event_type: EventType
  event_type_name: string
  occurred_at: string
  recorded_by: number | null
  source: 'manual' | 'driver_app'
  note: string
  created_at: string
}

export interface CargoTransfer {
  id: number
  consignment: number
  consignment_name: string
  order: number
  order_number: string
  transfer_kind: TransferKind
  transfer_kind_name: string
  from_trip: number | null
  from_trip_number: string | null
  to_trip: number | null
  to_trip_number: string | null
  from_stop: number | null
  to_stop: number
  to_stop_city: string
  from_carrier: number | null
  from_carrier_name: string | null
  to_carrier: number | null
  to_carrier_name: string | null
  carrier_changed: boolean
  transferred_at: string
  weight_kg: string | null
  volume_m3: string | null
  pallets: number | null
  status: TransferStatus
  initiated_by: number | null
  source: 'manual' | 'driver_app'
  confirmed_by: number | null
  confirmed_at: string | null
  reverses: number | null
  reversed_by: number | null
  note: string
  created_at: string
}

export interface TransferPayload {
  transfer_kind: TransferKind
  to_stop: number
  from_trip?: number | null
  to_trip?: number | null
  to_carrier?: number | null
  transferred_at?: string
  note?: string
}

export interface TransferListParams {
  consignment: number | null
  status: string
  kind: string
  pending: boolean
  page: number
  pageSize: number
}
