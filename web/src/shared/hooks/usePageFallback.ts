import { useEffect } from 'react'
import { ApiError } from '../api/errors'

/** Страница за последней (DRF отвечает 404) - вместо голой ошибки возвращаемся на первую страницу. */
export function usePageFallback(error: unknown, page: number, toFirstPage: () => void): void {
  const outOfRange = page > 1 && error instanceof ApiError && error.status === 404
  useEffect(() => {
    if (outOfRange) toFirstPage()
  }, [outOfRange, toFirstPage])
}
