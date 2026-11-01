import { useTranslation } from 'react-i18next'
import { Badge, type Tone } from '../../shared/ui/Badge'
import type { InvoiceStatus } from './types'

const TONES: Record<InvoiceStatus, Tone> = {
  draft: 'neutral', issued: 'info', partial: 'warning', paid: 'success', overdue: 'danger', cancelled: 'neutral',
}

export function StatusBadge({ status }: { status: InvoiceStatus }) {
  const { t } = useTranslation()
  return <Badge tone={TONES[status]}>{t(`finance.status.${status}`)}</Badge>
}

/** Номер счёта либо подпись черновика. */
export function invoiceLabel(invoice: { id: number; number: string }, t: (key: string, o?: Record<string, unknown>) => string): string {
  return invoice.number || t('finance.invoices.draftNo', { id: invoice.id })
}
