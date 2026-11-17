import { useTranslation } from 'react-i18next'
import { Button } from './Button'
import { ChevronLeft, ChevronRight } from './icons'
import { SelectBox } from './SelectBox'

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
    <nav
      aria-label={t('pagination.label')}
      className="flex items-center justify-between gap-3 rounded-card border border-line bg-surface px-3 py-2 text-xs text-muted shadow-card"
    >
      <span className="whitespace-nowrap tabular-nums">{t('pagination.range', { from, to, total: count })}</span>
      <div className="flex items-center gap-2">
        {onPageSize ? (
          <label className="flex items-center gap-1.5 whitespace-nowrap max-md:hidden">
            {t('pagination.pageSize')}
            <SelectBox>
              <select
                value={pageSize}
                onChange={(event) => {
                  onPageSize(Number(event.target.value))
                }}
                className="h-8 appearance-none rounded-control border border-line bg-surface pl-2 pr-7 text-sm text-ink"
              >
                {PAGE_SIZES.map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>
            </SelectBox>
          </label>
        ) : null}
        <span aria-hidden="true" className="h-5 w-px bg-line max-md:hidden" />
        <Button
          className="h-8! gap-1! px-2.5! text-xs!"
          aria-label={t('pagination.prev')}
          disabled={page <= 1}
          onClick={() => {
            onPage(page - 1)
          }}
        >
          <ChevronLeft className="size-4" aria-hidden="true" />
          <span className="max-md:sr-only">{t('pagination.prev')}</span>
        </Button>
        <span aria-live="polite" className="min-w-[4.5rem] whitespace-nowrap text-center tabular-nums text-ink">{t('pagination.page', { page, pages })}</span>
        <Button
          className="h-8! gap-1! px-2.5! text-xs!"
          aria-label={t('pagination.next')}
          disabled={page >= pages}
          onClick={() => {
            onPage(page + 1)
          }}
        >
          <span className="max-md:sr-only">{t('pagination.next')}</span>
          <ChevronRight className="size-4" aria-hidden="true" />
        </Button>
      </div>
    </nav>
  )
}
