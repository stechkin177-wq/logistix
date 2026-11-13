import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSession } from '../../shared/auth/useSession'
import { createLabel, deleteLabel, listLabels, setSubjectLabels, updateLabel } from './api'
import type { LabelSubject } from './types'

/** Метки компании. Список доступен тем, кто видит заказы, рейсы, клиентов или перевозчиков. */
export function useLabels(enabled = true) {
  const { hasPermission } = useSession()
  const allowed = ['orders', 'trips', 'clients', 'carriers'].some((s) => hasPermission(`${s}.view`))
  return useQuery({ queryKey: ['labels', 'list'], queryFn: ({ signal }) => listLabels(signal), enabled: enabled && allowed, staleTime: 30_000 })
}

const LIST_KEY: Record<LabelSubject, string> = { order: 'orders', trip: 'trips', client: 'clients', carrier: 'carriers' }

export function useSetSubjectLabels(kind: LabelSubject, id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (labels: number[]) => setSubjectLabels(kind, id, labels),
    onSuccess: () => qc.invalidateQueries({ queryKey: [LIST_KEY[kind]] }),
  })
}

function useInvalidateLabels() {
  const qc = useQueryClient()
  // название и цвет видны на объектах: обновляем и списки объектов
  return () => Promise.all(['labels', 'orders', 'trips', 'clients', 'carriers'].map((k) => qc.invalidateQueries({ queryKey: [k] })))
}

export function useCreateLabel() {
  const invalidate = useInvalidateLabels()
  return useMutation({ mutationFn: createLabel, onSuccess: invalidate })
}

export function useUpdateLabel() {
  const invalidate = useInvalidateLabels()
  return useMutation({ mutationFn: ({ id, body }: { id: number; body: { name?: string; color?: string } }) => updateLabel(id, body), onSuccess: invalidate })
}

export function useDeleteLabel() {
  const invalidate = useInvalidateLabels()
  return useMutation({ mutationFn: deleteLabel, onSuccess: invalidate })
}
