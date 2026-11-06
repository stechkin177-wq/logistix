import type { Invoice, Rate } from '../features/finance/types'
import { hv } from './orders'

export const VAT_RATES = [
  hv('vat_rate', 31, 'Без НДС', { code: 'none' }),
  hv('vat_rate', 32, 'НДС 0%', { code: '0' }),
  hv('vat_rate', 34, 'НДС 16%', { code: '16' }),
]

export function makeRate(over: Partial<Rate> = {}): Rate {
  return {
    id: 1, currency: { id: 12, code: 'USD', name: 'Доллар США' }, date: '2026-10-01', rate: '450.500000',
    created_at: '2026-10-01T05:00:00Z', ...over,
  }
}

export function makeInvoice(over: Partial<Invoice> = {}): Invoice {
  return {
    id: 1, direction: 'out', number: 'СЧ-2026-00001', external_number: '', status: 'issued', display_status: 'issued',
    client: { id: 7, name: 'ТОО Ромашка' }, carrier: null, order: { id: 5, number: 'ORD-2026-00005' }, trip: null,
    currency: { id: 11, code: 'KZT', name: 'Тенге' }, vat_rate: { id: 34, code: '16', name: 'НДС 16%' },
    issue_date: '2026-10-30', due_date: '2026-11-20', rate_to_kzt: '1.000000',
    totals: { net: '1000.00', vat: '160.00', gross: '1160.00' }, paid: '0.00', balance: '1160.00', comment: '',
    items: [{ id: 1, title: 'Перевозка', amount_net: '1000.00', line: 100 }], created_at: '2026-10-30T05:00:00Z',
    ...over,
  }
}
