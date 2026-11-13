export type MailSecurity = 'ssl' | 'starttls' | 'none'
export type MailState = 'draft' | 'sent' | 'failed'

/** Ящик компании: пароль сервер никогда не отдаёт, только признак has_password. */
export interface MailAccount {
  configured: boolean
  host?: string
  port?: number
  security?: MailSecurity
  username?: string
  has_password?: boolean
  from_email?: string
  from_name?: string
  is_active?: boolean
}

export interface MailAccountForm {
  host: string
  port: number
  security: MailSecurity
  username: string
  /** Пустая строка при изменении - прежний пароль сохраняется. */
  password: string
  from_email: string
  from_name: string
  is_active: boolean
}

export interface MailTemplate {
  id: number
  name: string
  subject: string
  body: string
}

export interface MailMessage {
  id: number
  to: string[]
  cc: string[]
  subject: string
  body: string
  state: MailState
  error: string
  sent_at: string | null
  attempts: number
  order: number | null
  order_number: string | null
  trip: number | null
  trip_number: string | null
  client: number | null
  client_name: string | null
  created_by_name: string
  created_at: string
  attachments: { id: number; document: number | null; filename: string }[]
}

export interface MailCompose {
  to: string[]
  cc: string[]
  subject: string
  body: string
  order?: number | null
  trip?: number | null
  client?: number | null
  attachments?: number[]
  send: boolean
}

/** Привязка письма к объекту (для кнопки «Написать письмо» в карточках). */
export interface MailContext {
  order?: number
  trip?: number
  client?: number
  /** Адрес получателя по умолчанию (например, email клиента). */
  to?: string
}
