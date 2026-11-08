import type { ConsignmentRoute, OrderStop } from '../orders/types'

export interface ConsignmentPointRef {
  id: number
  kind: 'load' | 'unload'
  city: string
  window_from: string | null
}

export interface Consignment {
  id: number
  order: number
  order_number: string
  client: number
  client_name: string
  name: string
  weight_kg: string
  volume_m3: string
  pallets: number | null
  status_name: string
  points: ConsignmentPointRef[]
  /** Полный маршрут по порядку; может отсутствовать у старых ответов. */
  stops?: OrderStop[]
  route?: ConsignmentRoute
  trips_count: number
}

export interface ConsignmentListParams {
  q: string
  client: number | null
  withoutTrip: boolean
  page: number
  pageSize: number
}
