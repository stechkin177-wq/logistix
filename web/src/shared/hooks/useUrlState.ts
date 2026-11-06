import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'

/** Кодек одного параметра адреса: разбор любого мусора безопасен (возвращает значение по умолчанию). */
export interface Codec<T> {
  default: T
  parse(raw: string[]): T
  /** Строки для адреса; пустой массив - параметр убирается. */
  serialize(value: T): string[]
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

function isRealDate(value: string): boolean {
  if (!DATE_RE.test(value)) return false
  const [y = 0, m = 0, d = 0] = value.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d
}

export const codecs = {
  string: (fallback = ''): Codec<string> => ({
    default: fallback,
    parse: (raw) => raw[0] ?? fallback,
    serialize: (v) => (v === fallback ? [] : [v]),
  }),
  positiveInt: (fallback = 1): Codec<number> => ({
    default: fallback,
    parse: ([raw]) => {
      if (raw === undefined || !/^\d{1,9}$/.test(raw)) return fallback
      const n = Number(raw)
      return n >= 1 ? n : fallback
    },
    serialize: (v) => (v === fallback ? [] : [String(v)]),
  }),
  oneOf: <T extends string>(allowed: readonly T[], fallback: T): Codec<T> => ({
    default: fallback,
    parse: ([raw]) => allowed.find((a) => a === raw) ?? fallback,
    serialize: (v) => (v === fallback ? [] : [v]),
  }),
  /** Целое из допустимого набора (размер страницы). */
  choiceInt: (allowed: readonly number[], fallback: number): Codec<number> => ({
    default: fallback,
    parse: ([raw]) => allowed.find((a) => String(a) === raw) ?? fallback,
    serialize: (v) => (v === fallback ? [] : [String(v)]),
  }),
  /** Список положительных чисел: ?status=1,2&status=3. */
  numberList: (): Codec<number[]> => ({
    default: [],
    parse: (raw) =>
      raw
        .flatMap((r) => r.split(','))
        .filter((p) => /^\d{1,12}$/.test(p))
        .map(Number)
        .filter((n, i, all) => n > 0 && all.indexOf(n) === i),
    serialize: (v) => (v.length ? [v.join(',')] : []),
  }),
  /** Один числовой id или null. */
  id: (): Codec<number | null> => ({
    default: null,
    parse: ([raw]) => (raw !== undefined && /^\d{1,12}$/.test(raw) && Number(raw) > 0 ? Number(raw) : null),
    serialize: (v) => (v === null ? [] : [String(v)]),
  }),
  flag: (): Codec<boolean> => ({
    default: false,
    parse: ([raw]) => raw === '1',
    serialize: (v) => (v ? ['1'] : []),
  }),
  /** Дата YYYY-MM-DD (несуществующая - пусто). */
  date: (): Codec<string> => ({
    default: '',
    parse: ([raw]) => (raw !== undefined && isRealDate(raw) ? raw : ''),
    serialize: (v) => (v ? [v] : []),
  }),
}

export type Schema = Record<string, Codec<unknown>>
type CodecValue<C> = C extends Codec<infer T> ? T : never
export type UrlState<S extends Schema> = { [K in keyof S]: CodecValue<S[K]> }

/**
 * Состояние списка (фильтры, страница, сортировка) в строке запроса. Мусор в адресе не падает, а даёт
 * значения по умолчанию; значения по умолчанию в адрес не пишутся; чужие параметры сохраняются.
 * setState(patch) обновляет часть полей; изменение фильтра без явной page сбрасывает страницу (pageKey).
 */
export function useUrlState<S extends Schema>(
  schema: S,
  options: { pageKey?: keyof S & string } = {},
): [UrlState<S>, (patch: Partial<UrlState<S>>, opts?: { replace?: boolean }) => void] {
  const [params, setParams] = useSearchParams()
  const search = params.toString()

  const state = useMemo(() => {
    const current = new URLSearchParams(search)
    const result: Record<string, unknown> = {}
    for (const [key, codec] of Object.entries(schema)) {
      result[key] = codec.parse(current.getAll(key))
    }
    return result as UrlState<S>
  }, [search, schema])

  const { pageKey } = options
  const setState = useCallback(
    (patch: Partial<UrlState<S>>, opts: { replace?: boolean } = {}) => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous)
          const entries = { ...patch } as Record<string, unknown>
          if (pageKey && !(pageKey in entries) && Object.keys(entries).length > 0) entries[pageKey] = 1
          for (const [key, value] of Object.entries(entries)) {
            const codec = schema[key]
            if (!codec) continue
            next.delete(key)
            for (const item of codec.serialize(value)) next.append(key, item)
          }
          return next
        },
        { replace: opts.replace ?? false },
      )
    },
    [pageKey, schema, setParams],
  )

  return [state, setState]
}
