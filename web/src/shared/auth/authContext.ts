import { createContext } from 'react'
import type { AuthContextKind } from './tokens'

/** Итог первого шага входа: вошли, либо нужен код TOTP (setup - первое подключение аутентификатора). */
export type LoginResult = { kind: 'done'; context: AuthContextKind } | { kind: 'totp'; challenge: string; setup: boolean }

export interface AuthContextValue {
  /** Есть ли токены (после перезагрузки - refresh в sessionStorage). */
  hasTokens: boolean
  /** Подписка заблокирована: показывается экран «Доступ приостановлен». */
  blocked: boolean
  /** Текущий контекст: компания или Центр управления платформы. */
  context: AuthContextKind
  /** Платформенная роль -> Центр управления; владельцу платформы дополнительно нужен код TOTP. */
  login: (login: string, password: string) => Promise<LoginResult>
  /** Второй шаг входа: код из приложения-аутентификатора. */
  completeTotp: (challenge: string, code: string) => Promise<AuthContextKind>
  logout: () => void
  switchCompany: (companyId: number) => Promise<void>
  /** В Центр управления; владельцу нужен свежий код TOTP. */
  switchToPlatform: (code?: string) => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
