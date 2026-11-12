import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { WriteButton } from '../../shared/ui/WriteButton'
import { TypedDocumentForm, documentSummary } from '../doctypes/TypedDocumentForm'
import { useChildList, useCreateChild, useDeleteChild } from './hooks'
import type { Vehicle } from './types'

interface Row { id: number; kind: string; doc_type_name?: string; number?: string; expires_at?: string | null }

/** Документы техники: типы и поля настраивает компания (раздел «Настройки → Типы документов»). */
export function VehicleDocuments({ vehicle }: { vehicle: Vehicle }) {
  const { t } = useTranslation()
  const list = useChildList<Row>('vehicle-documents', vehicle.id)
  const create = useCreateChild('vehicle-documents')
  const remove = useDeleteChild('vehicle-documents')
  const subject = vehicle.kind === 'trailer' ? 'trailer' : 'tractor'

  return (
    <div className="space-y-3">
      {list.isError ? <p role="alert" className="text-sm text-red-600">{errorMessage(list.error, t)}</p> : null}
      {list.data && list.data.results.length === 0 ? <p className="text-sm text-muted">{t('fleet.noDocuments')}</p> : null}
      <ul className="divide-y divide-slate-200 text-sm">
        {list.data?.results.map((row) => (
          <li key={row.id} className="flex items-center justify-between gap-2 py-1.5">
            <span>{documentSummary(row, t(`fleet.docKind.${row.kind}`), t('fleet.until'))}</span>
            <WriteButton permission="fleet.delete" variant="ghost" aria-label={t('fleet.deleteRecord')} onClick={() => { remove.mutate(row.id) }}>
              {t('common.delete')}
            </WriteButton>
          </li>
        ))}
      </ul>
      <TypedDocumentForm subject={subject} issuedKey="starts_at" permission="fleet.create" owner={{ vehicle: vehicle.id }} create={create} addLabel={t('fleet.add')} />
    </div>
  )
}
