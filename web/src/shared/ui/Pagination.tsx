import { useTranslation } from 'react-i18next'
import { Button } from './Button'

/** Конверт постраничного ответа бэкенда (DRF PageNumberPagination, StandardPagination). */
export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export const PAGE_SIZES = [20, 50, 100] as const

interface Props {
  page: number
  pageSize: number
  count: number
  onPage: (page: number) => void
  onPageSize?: (size: number) => void
}

export function Pagination({ page, pageSize, count, onPage, onPageSize }: Props) {
  const { t } = useTranslation()
  const pages = Math.max(1, Math.ceil(count / pageSize))
  if (count === 0) return null
  const from = (page - 1) * pageSize + 1
  const to = Math.min(count, page * pageSize)
  return (
    <nav aria-label={t('pagination.label')} className="flex flex-wrap items-center justify-between gap-2 py-2 text-xs">
      <span>{t('pagination.range', { from, to, total: count })}</span>
      <div className="flex items-center gap-2">
        {onPageSize ? (
          <label className="flex items-center gap-1">
            {t('pagination.pageSize')}
            <select
              value={pageSize}
              onChange={(event) => {
                onPageSize(Number(event.target.value))
              }}
              className="h-7 rounded border border-slate-300 bg-white px-1 dark:border-slate-600 dark:bg-slate-900"
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <Button
          disabled={page <= 1}
          onClick={() => {
            onPage(page - 1)
          }}
        >
          {t('pagination.prev')}
        </Button>
        <span aria-live="polite">{t('pagination.page', { page, pages })}</span>
        <Button
          disabled={page >= pages}
          onClick={() => {
            onPage(page + 1)
          }}
        >
          {t('pagination.next')}
        </Button>
      </div>
    </nav>
  )
}
