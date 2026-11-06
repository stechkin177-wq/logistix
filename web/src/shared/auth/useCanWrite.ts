import { useSession } from './useSession'

/** Можно ли выполнять запись: есть право И подписка не readonly/blocked. UI только скрывает, сервер проверяет. */
export function useCanWrite(permission?: string): boolean {
  const { session, hasPermission, subscriptionStatus } = useSession()
  if (!session) return false
  if (subscriptionStatus === 'readonly' || subscriptionStatus === 'blocked') return false
  return permission === undefined || hasPermission(permission)
}

export function useWriteBlockReason(permission?: string): 'readonly' | 'permission' | null {
  const { session, hasPermission, subscriptionStatus } = useSession()
  if (!session) return 'permission'
  if (subscriptionStatus === 'readonly' || subscriptionStatus === 'blocked') return 'readonly'
  if (permission !== undefined && !hasPermission(permission)) return 'permission'
  return null
}
