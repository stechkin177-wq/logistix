import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { useSession } from '../../shared/auth/useSession'
import { Banner } from '../../shared/ui/Banner'
import { Card, CardHeader } from '../../shared/ui/Card'
import { DateTime } from '../../shared/ui/DateTime'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FileText } from '../../shared/ui/icons'
import { Spinner } from '../../shared/ui/Spinner'
import { useIssued } from './hooks'
import { DownloadButtons } from './IssuedDialog'
import type { IssuedFilters } from './types'

type Source = Pick<IssuedFilters, 'order' | 'trip' | 'client'>

/** Документы, выданные по записи (заказ, рейс, клиент): список со скачиванием и кнопки выдачи нового. */
export function EntityDocuments({ source, actions, hint }: { source: Source; actions?: ReactNode; hint?: string }) {
  const { t } = useTranslation()
  const { hasPermission, hasModule } = useSession()
  const canList = hasModule('documents') && hasPermission('documents.view')
  const list = useIssued({ ...source, kind: '', date_from: '', date_to: '', search: '', page: 1, pageSize: 50 }, canList)
  const [downloadError, setDownloadError] = useState('')
  const rows = list.data?.results ?? []

  return (
    <div className="space-y-3">
      {downloadError ? <Banner kind="error">{downloadError}</Banner> : null}
      <Card>
        <CardHeader title={t('documents.title')} hint={hint} actions={actions} />
        {!canList ? <EmptyState icon={FileText} title={t('documents.entityNoList')} /> : null}
        {canList && list.isPending ? <div className="p-4"><Spinner label={t('common.loading')} /></div> : null}
        {canList && list.isError ? <div className="p-4"><Banner kind="error">{errorMessage(list.error, t)}</Banner></div> : null}
        {canList && list.data && rows.length === 0 ? <EmptyState icon={FileText} title={t('documents.entityEmpty')} hint={t('documents.entityEmptyHint')} /> : null}
        {rows.length > 0 ? (
          <ul className="divide-y divide-line text-sm">
            {rows.map((doc) => (
              <li key={doc.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
                <span className="min-w-0">
                  <span className="font-medium">{doc.number}</span>
                  <span className="ml-2 text-muted">{t(`documents.kind.${doc.kind}`)} · <DateTime value={doc.issue_date} dateOnly /></span>
                </span>
                <span className="flex gap-1"><DownloadButtons doc={doc} onError={setDownloadError} /></span>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
    </div>
  )
}
