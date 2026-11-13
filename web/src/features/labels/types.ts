export const LABEL_COLORS = ['slate', 'red', 'orange', 'amber', 'green', 'teal', 'blue', 'violet', 'pink'] as const
export type LabelColor = (typeof LABEL_COLORS)[number]

/** Метка в ответах объектов (заказ, рейс, клиент, перевозчик). */
export interface LabelRef {
  id: number
  name: string
  color: string
}

export interface Label extends LabelRef {
  usage_count: number
  created_at: string
}

export type LabelSubject = 'order' | 'trip' | 'client' | 'carrier'
