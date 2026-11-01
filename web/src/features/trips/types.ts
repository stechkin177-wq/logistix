export interface TripCargo {
  id: number
  name: string
  order: number
  order_number: string
}

export interface Trip {
  id: number
  number: string
  carrier: number | null
  carrier_name: string | null
  vehicle_plate: string
  driver_name: string
  /** Денежная строка API. */
  price: string
  currency: number
  status: number
  status_name: string
  is_consolidated: boolean
  orders: { id: number; number: string }[]
  consignments: TripCargo[]
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
  consignments: number[]
  carrier: number | null
  vehicle_plate: string
  driver_name: string
  price: string
  currency?: number
}

/** PATCH рейса: ТОЛЬКО эти поля (номер, статус, грузы и признак сборного меняются другими путями). */
export interface TripPatchPayload {
  carrier: number | null
  vehicle_plate: string
  driver_name: string
  price: string
  currency?: number
}
