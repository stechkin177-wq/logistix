import { api } from '../../shared/api/client'
import type { Label, LabelRef, LabelSubject } from './types'

export const listLabels = (signal?: AbortSignal) => api.get<Label[]>('/labels/', undefined, { signal })
export const createLabel = (body: { name: string; color: string }) => api.post<Label>('/labels/', body)
export const updateLabel = (id: number, body: { name?: string; color?: string }) => api.patch<Label>(`/labels/${String(id)}/`, body)
export const deleteLabel = (id: number) => api.delete(`/labels/${String(id)}/`)
export const setSubjectLabels = (kind: LabelSubject, id: number, labels: number[]) =>
  api.put<LabelRef[]>(`/labels/subjects/${kind}/${String(id)}/`, { labels })
