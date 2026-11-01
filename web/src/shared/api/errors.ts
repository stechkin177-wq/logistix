/** Ошибка API, собранная из тела ответа бэкенда: {"detail","code"} или словарь ошибок полей DRF. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: string
  readonly fields: Record<string, string[]>

  constructor(
    status: number,
    code: string,
    detail: string,
    fields: Record<string, string[]> = {},
  ) {
    super(detail || code)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
    this.fields = fields
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function messages(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.flatMap(messages)
  if (isRecord(value)) return Object.values(value).flatMap(messages)
  return []
}

export function buildApiError(status: number, body: unknown): ApiError {
  if (!isRecord(body)) return new ApiError(status, `http_${status}`, '')
  const { detail, code, ...rest } = body
  if (typeof detail === 'string') {
    return new ApiError(status, typeof code === 'string' ? code : `http_${status}`, detail)
  }
  const fields: Record<string, string[]> = {}
  for (const [name, value] of Object.entries(rest)) {
    const list = messages(value)
    if (list.length > 0) fields[name] = list
  }
  const first = Object.values(fields)[0]?.[0] ?? ''
  return new ApiError(status, typeof code === 'string' ? code : 'validation_error', first, fields)
}

type Translate = (key: string) => string

/** Сообщение для пользователя: известные коды - через i18n, остальное - нейтральный текст. */
export function errorMessage(error: unknown, t: Translate): string {
  if (!(error instanceof ApiError)) return t('errors.unknown')
  switch (error.code) {
    case 'network_error':
      return t('errors.network')
    case 'subscription_blocked':
      return t('errors.subscriptionBlocked')
    case 'subscription_readonly':
      return t('errors.subscriptionReadonly')
    case 'module_disabled':
      return t('errors.moduleDisabled')
    case 'limit_exceeded':
      return t('errors.limitExceeded')
  }
  if (error.status === 403) return t('errors.forbidden')
  if (error.status === 404) return t('errors.notFound')
  if (error.status === 429) return t('errors.tooMany')
  if (error.status >= 500) return t('errors.server')
  return t('errors.unknown')
}
