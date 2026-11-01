import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
import { clearTokens } from '../shared/auth/tokens'

afterEach(() => {
  cleanup()
  clearTokens()
  window.sessionStorage.clear()
  window.localStorage.clear()
  document.documentElement.removeAttribute('style')
  document.documentElement.classList.remove('dark')
})
