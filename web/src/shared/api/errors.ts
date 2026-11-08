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

/**
 * Плоские пути ошибок полей: вложенные ответы DRF ({"consignments":[{"points":[{},{"city":["x"]}]}]})
 * превращаются в {"consignments.0.points.1.city": ["x"]}.
 */
function collect(path: string, value: unknown, out: Record<string, string[]>): void {
  if (typeof value === 'string') {
    ;(out[path] ??= []).push(value)
  } else if (Array.isArray(value)) {
    value.forEach((item, index) => {
      collect(typeof item === 'string' ? path : `${path}.${index}`, item, out)
    })
  } else if (isRecord(value)) {
    for (const [key, item] of Object.entries(value)) collect(path ? `${path}.${key}` : key, item, out)
  }
}

export function buildApiError(status: number, body: unknown): ApiError {
  // DRF: ValidationError("текст") приходит списком строк
  if (Array.isArray(body)) {
    const fields: Record<string, string[]> = {}
    collect('non_field_errors', body, fields)
    return new ApiError(status, 'validation_error', fields.non_field_errors?.[0] ?? '', fields)
  }
  if (!isRecord(body)) return new ApiError(status, `http_${status}`, '')
  const { detail, code, ...rest } = body
  if (typeof detail === 'string') {
    return new ApiError(status, typeof code === 'string' ? code : `http_${status}`, detail)
  }
  const fields: Record<string, string[]> = {}
  for (const [name, value] of Object.entries(rest)) collect(name, value, fields)
  const first = Object.values(fields)[0]?.[0] ?? ''
  return new ApiError(status, typeof code === 'string' ? code : 'validation_error', first, fields)
}

type Translate = (key: string) => string

const FINANCE_CODES = [
  'rate_missing', 'currency_mismatch', 'party_mismatch', 'item_already_invoiced', 'payment_exceeds_balance',
  'invoice_not_editable', 'invoice_has_payments', 'invoice_exceeds_order_income', 'credit_limit_exceeded', 'invoice_empty',
  'line_unavailable', 'line_invoiced', 'allocation_mismatch', 'order_not_in_trip', 'expense_exists', 'invalid_vat', 'amount_too_large', 'payment_not_restorable',
  'finance_frozen', 'legacy_lines_readonly', 'period_closed', 'backdating_forbidden', 'period_reason_required', 'completed_status_missing',
  'switch_refused', 'allocation_exceeds', 'field_not_editable', 'status_code_taken', 'status_already_coded',
]
const DOCUMENT_CODES = [
  'template_invalid', 'template_missing', 'template_too_large', 'source_not_ready', 'letter_invalid',
  'render_unavailable', 'pdf_unavailable', 'kind_invalid',
]

const MODULE_CODES = [
  'module_unknown', 'module_core', 'module_retired', 'module_not_in_plan', 'module_requires', 'module_has_dependents',
  'module_protected',
]

/** Код ошибки сервера -> ключ i18n перевода (разделы finance, documents и модули компании). */
const KNOWN_CODES = new Map<string, string>([
  ...FINANCE_CODES.map((code): [string, string] => [code, `errors.finance.${code}`]),
  ...DOCUMENT_CODES.map((code): [string, string] => [code, `errors.documents.${code}`]),
  ...MODULE_CODES.map((code): [string, string] => [code, `errors.modules.${code}`]),
])

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
    case 'contact_in_use':
      return t('errors.contactInUse')
    case 'number_conflict':
      return t('errors.numberConflict')
  }
  const known = KNOWN_CODES.get(error.code)
  if (known) {
    // сервер называет метку, строку и причину: для этих кодов его текст точнее общего перевода
    if ((error.code === 'template_invalid' || error.code === 'source_not_ready') && error.detail) return error.detail
    return t(known)
  }
  if (error.status === 409) return error.detail || t('errors.conflict')
  if ((error.status === 400 || error.status === 422) && error.detail) return error.detail
  // 403 с текстом сервера (нельзя менять свою роль, нельзя выдать чужие права) показываем как есть
  if (error.status === 403) return error.detail || t('errors.forbidden')
  if (error.status === 404) return t('errors.notFound')
  if (error.status === 429) return t('errors.tooMany')
  if (error.status >= 500) return t('errors.server')
  return t('errors.unknown')
}
