export interface OrderPoint {
  id?: number
  kind: 'load' | 'unload'
  window_from: string
  window_to: string | null
  country: number | null
  country_name?: string | null
  city: string
  street: string
  method: number | null
  method_name?: string | null
  contact: string
  postal_code: string
  lat: string | null
  lng: string | null
  note: string
}

export type StopKind = 'load' | 'unload' | 'transit' | 'transfer' | 'customs'
export type StopStatus = 'planned' | 'arrived' | 'done' | 'skipped'

/** Остановка маршрута груза (stops): точка с порядком, видом, статусом и долями. */
export interface OrderStop extends Omit<OrderPoint, 'kind'> {
  kind: StopKind
  seq: number
  status: StopStatus
  arrived_at: string | null
  done_at: string | null
  weight_kg: string | null
  volume_m3: string | null
  pallets: number | null
}

/** Рейс, покрывающий отрезок маршрута груза (по неотменённым участкам). */
export interface CoverageTrip {
  id: number
  number: string
  status: string
}

/** Отрезок маршрута между соседними остановками и его покрытие участками рейсов. */
export interface CoverageSegment {
  from_stop: number
  to_stop: number
  from_seq: number
  to_seq: number
  covered: boolean
  legs: number[]
  trips: CoverageTrip[]
}

export interface RouteCoverage {
  segments: CoverageSegment[]
  uncovered: CoverageSegment[]
  fully_assigned: boolean
}

/** Маршрут груза: остановки и покрытие (route в ответе API груза). */
export interface ConsignmentRoute {
  stops: OrderStop[]
  coverage: RouteCoverage
}

export interface OrderConsignment {
  id: number
  name: string
  weight_kg: string
  volume_m3: string
  pallets: number
  packaging: number | null
  packaging_name: string | null
  status: number
  status_name: string
  /** Устаревшее поле: первая погрузка и последняя выгрузка маршрута. */
  points: OrderPoint[]
  /** Полный маршрут по порядку (может отсутствовать у старых ответов/фикстур). */
  stops?: OrderStop[]
  route?: ConsignmentRoute
  /** Местонахождение груза (производное, считает сервер). */
  location_status?: import('../tracking/types').LocationStatus
  current_stop?: number | null
  created_at: string
}

export interface OrderHistoryEntry {
  id: number
  from_status: number | null
  from_status_name: string | null
  to_status: number
  to_status_name: string
  user: number | null
  created_at: string
}

export interface Order {
  id: number
  number: string
  client: number
  client_name: string
  client_ref: string
  contract_number: string
  contact: number | null
  manager: number
  manager_name: string
  forwarder: number | null
  extra_managers: number[]
  legal_entity: number
  client_rate: string
  currency: number
  transport_condition: number | null
  delivery_days: number | null
  payment_delay_days: number | null
  payment_delay_condition: number | null
  comment: string
  status: number
  status_name: string
  completed_at: string | null
  route: string
  has_carrier: boolean
  revenue: string | null
  cost: string | null
  profit: string | null
  margin_pct: string | null
  consignments: OrderConsignment[]
  history?: OrderHistoryEntry[]
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface OrderListFilters {
  q: string
  status: number[]
  client: number | null
  carrier: number | null
  loading_from: string
  loading_to: string
  created_from: string
  created_to: string
  completed_from: string
  completed_to: string
  unassigned: boolean
}

export interface OrderListParams extends OrderListFilters {
  ordering: string
  page: number
  pageSize: number
}

export interface BoardCard {
  id: number
  number: string
  client: string
  route: string
  carriers: string[]
  rate: string
  currency: string
  loading_at: string | null
  has_carrier: boolean
}

export interface BoardColumn {
  status: { id: number; name: string }
  count: number
  orders: BoardCard[]
  has_more: boolean
}

export interface OrderLine {
  id: number
  order: number
  order_number: string
  title: string
  category: string
  income: string
  expense: string
  date: string
  is_base: boolean
  created_at: string
  updated_at: string
}

export interface OrderLinePayload {
  order: number
  title: string
  category: string
  income: string
  expense: string
  date: string
}

export interface TripRef {
  id: number
  number: string
  carrier_name: string | null
  status_name: string
  is_consolidated: boolean
  vehicle_plate: string
  driver_name: string
  orders: { id: number; number: string }[]
}
