import { ApiError, errorMessage } from '../api/errors'

type Translate = (key: string) => string

export interface FormErrors {
  /** Ошибки полей по плоскому пути: "name", "contacts.0.phone", "consignments.0.points.1.city". */
  fields: Record<string, string>
  /** Ошибка уровня формы: non_field_errors, 409, лимиты, подписка, сеть, а также ошибки полей без места в форме. */
  banner: string | undefined
}

export const NO_ERRORS: FormErrors = { fields: {}, banner: undefined }

/**
 * Разбор ошибки мутации для формы. known(path) - есть ли в форме поле с таким путём; ошибки неизвестных
 * путей не теряются, а попадают в баннер. Ошибки полей приходят на русском с сервера (как есть).
 */
export function serverErrors(error: unknown, t: Translate, known: (path: string) => boolean = () => true): FormErrors {
  if (error === null || error === undefined) return NO_ERRORS
  if (!(error instanceof ApiError) || Object.keys(error.fields).length === 0) {
    return { fields: {}, banner: errorMessage(error, t) }
  }
  const fields: Record<string, string> = {}
  const extra: string[] = []
  for (const [path, messages] of Object.entries(error.fields)) {
    const text = messages.join(' ')
    if (path === 'non_field_errors') extra.push(text)
    else if (known(path)) fields[path] = text
    else extra.push(`${path}: ${text}`)
  }
  return { fields, banner: extra.length > 0 ? extra.join(' ') : undefined }
}
