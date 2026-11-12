import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Banner } from './Banner'
import { Button } from './Button'
import { Spinner } from './Spinner'

export interface Column<T> {
  key: string
  header: ReactNode
  /** Текст заголовка для aria-label кнопки сортировки (если header не строка). */
  headerLabel?: string
  cell: (row: T) => ReactNode
  /** Значение параметра ordering API; без него колонка не сортируется. */
  sortKey?: string
  className?: string
  align?: 'left' | 'right'
}

interface Props<T> {
  columns: Column<T>[]
  rows: T[] | undefined
  rowKey: (row: T) => string | number
  loading?: boolean
  /** Уже переведённый текст ошибки загрузки. */
  error?: string
  onRetry?: () => void
  /** Что показать при пустом списке (EmptyState с CTA). */
  empty?: ReactNode
  /** Текущее значение ordering ("name" / "-name"). */
  ordering?: string
  onOrderingChange?: (ordering: string) => void
  caption: string
}

/** Плотная таблица: горизонтальный скролл, состояния loading/error/empty, сортировка через ordering API. */
export function DataTable<T>({
  columns, rows, rowKey, loading, error, onRetry, empty, ordering, onOrderingChange, caption,
}: Props<T>) {
  const { t } = useTranslation()

  const toggle = (sortKey: string) => {
    onOrderingChange?.(ordering === sortKey ? `-${sortKey}` : sortKey)
  }

  let body: ReactNode = null
  if (error) {
    body = (
      <div className="space-y-2 p-3">
        <Banner kind="error">{error}</Banner>
        {onRetry ? <Button onClick={onRetry}>{t('table.retry')}</Button> : null}
      </div>
    )
  } else if (loading && !rows) {
    body = (
      <div className="p-4">
        <Spinner label={t('table.loading')} />
      </div>
    )
  } else if (rows && rows.length === 0) {
    body = <div>{empty}</div>
  }

  return (
    <div className="overflow-hidden rounded-card border border-line bg-surface shadow-card">
      <div className="thin-scroll overflow-x-auto">
        {/* на узком экране строки превращаются в карточки: подпись колонки берётся из data-label */}
        <table className="w-full border-collapse text-left text-sm max-md:block md:min-w-max" aria-busy={loading ? true : undefined}>
          <caption className="sr-only">{caption}</caption>
          <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted max-md:sr-only">
            <tr>
              {columns.map((column) => {
                const sorted =
                  column.sortKey === undefined
                    ? undefined
                    : ordering === column.sortKey
                      ? 'ascending'
                      : ordering === `-${column.sortKey}`
                        ? 'descending'
                        : 'none'
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={sorted}
                    className={`whitespace-nowrap px-3 py-2.5 font-semibold ${column.align === 'right' ? 'text-right' : ''} ${column.className ?? ''}`}
                  >
                    {column.sortKey !== undefined && onOrderingChange ? (
                      <button
                        type="button"
                        onClick={() => {
                          toggle(column.sortKey ?? '')
                        }}
                        aria-label={t('table.sortBy', {
                          column: column.headerLabel ?? (typeof column.header === 'string' ? column.header : column.key),
                        })}
                        className="inline-flex items-center gap-1 hover:underline"
                      >
                        {column.header}
                        <span aria-hidden="true">{sorted === 'ascending' ? '▲' : sorted === 'descending' ? '▼' : ''}</span>
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          {rows && rows.length > 0 && !error ? (
            <tbody className={`max-md:block ${loading ? 'opacity-60' : ''}`}>
              {rows.map((row) => (
                <tr key={rowKey(row)} className="border-t border-line transition-colors hover:bg-surface-2 max-md:block max-md:px-3 max-md:py-2">
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      data-label={column.headerLabel ?? (typeof column.header === 'string' ? column.header : '')}
                      className={`px-3 py-2.5 align-middle max-md:flex max-md:items-baseline max-md:justify-between max-md:gap-3 max-md:px-0 max-md:py-1 max-md:text-right max-md:before:shrink-0 max-md:before:text-left max-md:before:text-xs max-md:before:text-muted max-md:before:content-[attr(data-label)] ${column.align === 'right' ? 'text-right' : ''} ${column.className ?? ''}`}
                    >
                      {column.cell(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          ) : null}
        </table>
      </div>
      {body}
    </div>
  )
}
