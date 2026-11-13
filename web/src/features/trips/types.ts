export interface TripCargo {
  id: number
  name: string
  order: number
  order_number: string
}

/** Остановка участка (кратко). */
export interface TripLegStop {
  id: number
  seq: number
  kind: string
  city: string
}

export type TripLegStatus = 'planned' | 'in_progress' | 'done' | 'cancelled'

/** Участок рейса: груз на отрезке маршрута между двумя остановками. */
export interface TripLeg {
  id: number
  consignment: number
  consignment_name: string
  order: number
  order_number: string
  /** null - прежняя связь «весь груз» без привязки к остановкам. */
  from_stop: TripLegStop | null
  to_stop: TripLegStop | null
  leg_seq: number
  status: TripLegStatus
  weight_kg: string | null
  volume_m3: string | null
  pallets: number | null
}

/** Явный участок в теле создания рейса; shares - доли (пусто - весь груз). */
export interface TripLegInput {
  consignment: number
  from_stop: number
  to_stop: number
  shares?: { weight_kg?: string | null; volume_m3?: string | null; pallets?: number | null }
}

export interface Trip {
  id: number
  number: string
  carrier: number | null
  carrier_name: string | null
  /** Договор с перевозчиком из реестра (необязательно). */
  contract?: number | null
  /** Ссылки на технику и водителя (модули fleet/drivers); текст ниже сервер заполняет по ним. */
  vehicle?: number | null
  trailer?: number | null
  driver?: number | null
  vehicle_plate: string
  driver_name: string
  /** Стоимость перевозчика: денежная строка API. */
  carrier_price: string
  /** Устаревший алиас carrier_price (удаляется отдельным решением); в коде не использовать. */
  price: string
  currency: number
  status: number
  status_name: string
  is_consolidated: boolean
  /** Время перехода в статус COMPLETED (ISO) или null; только чтение. */
  completed_at: string | null
  orders: { id: number; number: string }[]
  consignments: TripCargo[]
  /** Участки рейса (может отсутствовать у старых ответов). */
  legs?: TripLeg[]
  created_at: string
  updated_at: string
}

export interface TripListParams {
  q: string
  order: number | null
  status: number | null
  carrier: number | null
  consolidated: boolean
  page: number
  pageSize: number
}

/** Тело создания рейса: consignments - id грузов. */
export interface TripCreatePayload {
  /** Грузы на весь маршрут; для грузов с явными участками - в legs. */
  consignments: number[]
  legs?: TripLegInput[]
  carrier: number | null
  contract?: number | null
  vehicle?: number | null
  trailer?: number | null
  driver?: number | null
  vehicle_plate?: string
  driver_name?: string
  carrier_price: string
  currency?: number
}

/** PATCH рейса: ТОЛЬКО эти поля (номер, статус, грузы и признак сборного меняются другими путями). */
export interface TripPatchPayload {
  carrier: number | null
  vehicle?: number | null
  trailer?: number | null
  driver?: number | null
  vehicle_plate?: string
  driver_name?: string
  carrier_price: string
  currency?: number
}
