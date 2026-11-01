import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, errorMessage } from '../../../shared/api/errors'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { PAGE_SIZES } from '../../../shared/ui/Pagination'
import { safeFilename } from '../../../shared/api/filename'
import { exportOrders } from '../api'
import { NewOrderLink } from '../components/NewOrderLink'
import { EMPTY_FILTERS, OrderFilters, hasFilters } from '../components/OrderFilters'
import { OrdersBoard } from '../components/OrdersBoard'
import { OrdersTable } from '../components/OrdersTable'
import type { OrderListFilters, OrderListParams } from '../types'

const ORDERINGS = ['-created_at', 'created_at', 'number', '-number'] as const

export const ORDERS_SCHEMA = {
  q: codecs.string(''),
  status: codecs.numberList(),
  client: codecs.id(),
  carrier: codecs.id(),
  loading_from: codecs.date(),
  loading_to: codecs.date(),
  created_from: codecs.date(),
  created_to: codecs.date(),
  completed_from: codecs.date(),
  completed_to: codecs.date(),
  unassigned: codecs.flag(),
  ordering: codecs.oneOf(ORDERINGS, '-created_at'),
  page: codecs.positiveInt(1),
  pageSize: codecs.choiceInt(PAGE_SIZES, 50),
  view: codecs.oneOf(['list', 'board'] as const, 'list'),
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function OrdersPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(ORDERS_SCHEMA, { pageKey: 'page' })
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const filters: OrderListFilters = {
    q: state.q, status: state.status, client: state.client, carrier: state.carrier,
    loading_from: state.loading_from, loading_to: state.loading_to, created_from: state.created_from,
    created_to: state.created_to, completed_from: state.completed_from, completed_to: state.completed_to,
    unassigned: state.unassigned,
  }
  const params: OrderListParams = { ...filters, ordering: state.ordering, page: state.page, pageSize: state.pageSize }

  const download = async () => {
    setExporting(true)
    setExportError(null)
    try {
      const { blob, filename } = await exportOrders(params)
      saveBlob(blob, safeFilename(filename, 'orders.xlsx'))
    } catch (error) {
      setExportError(error instanceof ApiError && error.status === 400 && error.detail ? error.detail : errorMessage(error, t))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-base font-semibold">{t('nav.orders')}</h1>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label={t('orders.view')} className="inline-flex overflow-hidden rounded border border-slate-300 dark:border-slate-600">
            {(['list', 'board'] as const).map((view) => (
              <button
                key={view}
                type="button"
                aria-pressed={state.view === view}
                onClick={() => { setState({ view }, { replace: true }) }}
                className={`h-8 px-3 text-sm ${state.view === view ? 'bg-brand-600 text-white' : 'bg-white text-slate-700 hover:bg-slate-50 dark:bg-slate-900 dark:text-slate-200'}`}
              >
                {t(view === 'list' ? 'orders.viewList' : 'orders.viewBoard')}
              </button>
            ))}
          </div>
          <Button onClick={() => void download()} disabled={exporting}>
            {exporting ? t('orders.exporting') : t('orders.excel')}
          </Button>
          <NewOrderLink />
        </div>
      </div>
      <OrderFilters
        value={filters}
        onChange={(patch, opts) => { setState(patch, opts) }}
      />
      {exportError ? <Banner kind="error">{exportError}</Banner> : null}
      {state.view === 'board' ? (
        <OrdersBoard filters={filters} />
      ) : (
        <OrdersTable
          params={params}
          filtered={hasFilters(filters)}
          onChange={({ ordering, ...rest }) => {
            const valid = ORDERINGS.find((o) => o === ordering)
            setState({ ...rest, ...(valid ? { ordering: valid } : {}) })
          }}
          onReset={() => { setState(EMPTY_FILTERS) }}
        />
      )}
    </div>
  )
}
