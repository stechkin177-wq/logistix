import { Banner } from './Banner'

/** Ошибка уровня формы (не привязанная к полю): non_field_errors, 409, лимиты, подписка, сеть. */
export function FormBanner({ message }: { message: string | undefined }) {
  return message ? <Banner kind="error">{message}</Banner> : null
}
