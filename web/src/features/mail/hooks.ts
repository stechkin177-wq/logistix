import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSession } from '../../shared/auth/useSession'
import {
  createMailTemplate, deleteMailTemplate, getMailAccount, getMailStatus, listMailMessages, listMailTemplates, resendMail,
  saveMailAccount, sendMail, testMailAccount, updateMailTemplate, type MailFilters,
} from './api'

/** Можно ли писать письма: есть право отправки и ящик компании настроен. */
export function useMailStatus() {
  const { hasPermission } = useSession()
  const allowed = hasPermission('mail.send')
  const q = useQuery({ queryKey: ['mail', 'status'], queryFn: ({ signal }) => getMailStatus(signal), enabled: allowed, staleTime: 60_000 })
  return { allowed, configured: q.data?.configured ?? false, loading: q.isPending && allowed }
}

export const useMailAccount = () => useQuery({ queryKey: ['mail', 'account'], queryFn: ({ signal }) => getMailAccount(signal) })
export const useMailTemplates = (enabled = true) =>
  useQuery({ queryKey: ['mail', 'templates'], queryFn: ({ signal }) => listMailTemplates(signal), enabled })
export const useMailMessages = (f: MailFilters) =>
  useQuery({ queryKey: ['mail', 'messages', f], queryFn: ({ signal }) => listMailMessages(f, signal), placeholderData: keepPreviousData })

function useInvalidateMail() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: ['mail'] })
}

export function useSaveMailAccount() {
  const invalidate = useInvalidateMail()
  return useMutation({ mutationFn: saveMailAccount, onSuccess: invalidate })
}
export const useTestMailAccount = () => useMutation({ mutationFn: testMailAccount })
export function useSendMail() {
  const invalidate = useInvalidateMail()
  return useMutation({ mutationFn: sendMail, onSuccess: invalidate })
}
export function useResendMail() {
  const invalidate = useInvalidateMail()
  return useMutation({ mutationFn: resendMail, onSuccess: invalidate })
}
export function useCreateMailTemplate() {
  const invalidate = useInvalidateMail()
  return useMutation({ mutationFn: createMailTemplate, onSuccess: invalidate })
}
export function useUpdateMailTemplate() {
  const invalidate = useInvalidateMail()
  return useMutation({ mutationFn: ({ id, body }: { id: number; body: Parameters<typeof updateMailTemplate>[1] }) => updateMailTemplate(id, body), onSuccess: invalidate })
}
export function useDeleteMailTemplate() {
  const invalidate = useInvalidateMail()
  return useMutation({ mutationFn: deleteMailTemplate, onSuccess: invalidate })
}
