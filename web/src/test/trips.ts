import type { Consignment } from '../features/consignments/types'
import type { Trip } from '../features/trips/types'
import { hv } from './orders'

export const TRIP_STATUSES = [hv('trip_status', 21, 'Планируется', { is_initial: true }), hv('trip_status', 22, 'В пути'), hv('trip_status', 23, 'Завершён', { is_final: true })]

export function makeCargo(over: Partial<Consignment> = {}): Consignment {
  return {
    id: 31, order: 5, order_number: 'ORD-2026-00005', client: 7, client_name: 'ТОО Ромашка', name: 'Станки', weight_kg: '1200.00',
    volume_m3: '8.50', pallets: 4, status_name: 'Принят', trips_count: 0,
    points: [
      { id: 1, kind: 'load', city: 'Алматы', window_from: '2026-11-05T04:00:00Z' },
      { id: 2, kind: 'unload', city: 'Астана', window_from: '2026-11-08T04:00:00Z' },
    ],
    ...over,
  }
}

export function makeTrip(over: Partial<Trip> = {}): Trip {
  return {
    id: 90, number: 'ORD-2026-00005-1', carrier: 6, carrier_name: 'ИП Быстров', vehicle_plate: '123ABC02', driver_name: 'Иван',
    price: '100000.00', currency: 11, status: 21, status_name: 'Планируется', is_consolidated: false,
    orders: [{ id: 5, number: 'ORD-2026-00005' }],
    consignments: [{ id: 31, name: 'Станки', order: 5, order_number: 'ORD-2026-00005' }],
    created_at: '2026-10-30T05:00:00Z', updated_at: '2026-10-30T05:00:00Z',
    ...over,
  }
}
