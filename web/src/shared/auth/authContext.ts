import { createContext } from 'react'

export interface AuthContextValue {
  /** Есть ли токены (после перезагрузки - refresh в sessionStorage). */
  hasTokens: boolean
  /** Подписка заблокирована: показывается экран «Доступ приостановлен». */
  blocked: boolean
  login: (login: string, password: string) => Promise<void>
  logout: () => void
  switchCompany: (companyId: number) => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
