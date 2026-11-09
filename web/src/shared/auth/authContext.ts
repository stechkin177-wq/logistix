import { createContext } from 'react'
import type { AuthContextKind } from './tokens'

export interface AuthContextValue {
  /** Есть ли токены (после перезагрузки - refresh в sessionStorage). */
  hasTokens: boolean
  /** Подписка заблокирована: показывается экран «Доступ приостановлен». */
  blocked: boolean
  /** Текущий контекст: компания или Центр управления платформы. */
  context: AuthContextKind
  /** Возвращает контекст, в который попал пользователь (платформенная роль -> Центр управления). */
  login: (login: string, password: string) => Promise<AuthContextKind>
  logout: () => void
  switchCompany: (companyId: number) => Promise<void>
  switchToPlatform: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
