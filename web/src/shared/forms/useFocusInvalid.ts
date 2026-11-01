import { useEffect, type RefObject } from 'react'

/** После появления ошибок переводит фокус на первое невалидное поле формы (a11y). */
export function useFocusInvalid(form: RefObject<HTMLElement | null>, trigger: unknown): void {
  useEffect(() => {
    if (!trigger) return
    form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
  }, [form, trigger])
}
