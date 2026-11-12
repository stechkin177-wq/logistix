import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FIELD_CLASS } from './fieldStyles'
import { X } from './icons'
import { FormField } from './FormField'

export interface ComboOption {
  id: number
  label: string
}

interface Props {
  label: string
  value: ComboOption | null
  onChange: (value: ComboOption | null) => void
  /** Поиск на сервере; signal отменяет устаревший запрос. */
  fetchOptions: (query: string, signal: AbortSignal) => Promise<ComboOption[]>
  /** Префикс ключа кэша (поиск добавляется автоматически). */
  queryKey: readonly unknown[]
  error?: string
  required?: boolean
  disabled?: boolean
  hideLabel?: boolean
  placeholder?: string
  fieldClassName?: string
  debounceMs?: number
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(value)
    }, ms)
    return () => {
      clearTimeout(timer)
    }
  }, [value, ms])
  return debounced
}

/** Выбор записи с серверным поиском (клиент, перевозчик): ARIA combobox + listbox, стрелки/Enter/Escape. */
export function Combobox({
  label, value, onChange, fetchOptions, queryKey, error, required, disabled, hideLabel, placeholder, fieldClassName,
  debounceMs = 250,
}: Props) {
  const { t } = useTranslation()
  const listId = useId()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState<string | null>(null) // null - показываем выбранное
  const [active, setActive] = useState(0)
  const search = useDebounced(text ?? '', debounceMs)

  const query = useQuery({
    queryKey: [...queryKey, 'combobox', search],
    queryFn: ({ signal }) => fetchOptions(search, signal),
    enabled: open && !disabled,
    staleTime: 15_000,
  })
  const options = query.data ?? []

  const pick = (option: ComboOption | null) => {
    onChange(option)
    setText(null)
    setOpen(false)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      setActive((i) => Math.min(options.length - 1, i + 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((i) => Math.max(0, i - 1))
    } else if (event.key === 'Enter' && open) {
      event.preventDefault()
      const option = options[active]
      if (option) pick(option)
    } else if (event.key === 'Escape' && open) {
      event.stopPropagation() // закрываем список, а не окно вокруг
      setOpen(false)
      setText(null)
    }
  }

  return (
    <FormField label={label} error={error} required={required} hideLabel={hideLabel} className={`relative ${fieldClassName ?? ''}`}>
      {(aria) => (
        <>
          <div className="relative">
            <input
              {...aria}
              role="combobox"
              aria-expanded={open}
              aria-controls={listId}
              aria-autocomplete="list"
              aria-activedescendant={open && options[active] ? `${listId}-${options[active].id}` : undefined}
              autoComplete="off"
              disabled={disabled}
              placeholder={placeholder ?? t('combobox.placeholder')}
              value={text ?? value?.label ?? ''}
              onChange={(event) => {
                setText(event.target.value)
                setActive(0)
                setOpen(true)
              }}
              onFocus={() => {
                setOpen(true)
              }}
              onBlur={() => {
                setOpen(false)
                setText(null)
              }}
              onKeyDown={onKeyDown}
              className={`${FIELD_CLASS} ${value ? 'pr-9' : ''}`}
            />
            {value && !disabled ? (
              <button
                type="button"
                aria-label={t('combobox.clear')}
                onClick={() => {
                  pick(null)
                }}
                className="absolute inset-y-0 right-0 px-2.5 text-muted hover:text-ink"
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            ) : null}
          </div>
          {open ? (
            <ul
              id={listId}
              role="listbox"
              aria-label={label}
              className="thin-scroll absolute z-30 mt-1 max-h-60 w-full overflow-auto rounded-control border border-line bg-surface text-sm shadow-pop"
            >
              {query.isPending ? (
                <li className="px-3 py-2 text-muted">{t('combobox.loading')}</li>
              ) : query.isError ? (
                <li className="px-3 py-2 text-red-600">{t('common.loadFailed')}</li>
              ) : options.length === 0 ? (
                <li className="px-3 py-2 text-muted">{t('common.noResults')}</li>
              ) : (
                options.map((option, index) => (
                  <li
                    key={option.id}
                    id={`${listId}-${option.id}`}
                    role="option"
                    aria-selected={value?.id === option.id}
                    onMouseDown={(event) => {
                      event.preventDefault() // фокус остаётся в поле
                      pick(option)
                    }}
                    onMouseEnter={() => {
                      setActive(index)
                    }}
                    className={`cursor-pointer px-3 py-2 ${index === active ? 'bg-brand-50 text-brand-900 dark:bg-slate-700 dark:text-white' : ''}`}
                  >
                    {option.label}
                  </li>
                ))
              )}
            </ul>
          ) : null}
        </>
      )}
    </FormField>
  )
}
