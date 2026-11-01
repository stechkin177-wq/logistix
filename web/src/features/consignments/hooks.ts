import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { listConsignments } from './api'
import type { ConsignmentListParams } from './types'

export function useConsignmentList(params: ConsignmentListParams, enabled = true) {
  return useQuery({
    queryKey: ['consignments', 'list', params],
    queryFn: ({ signal }) => listConsignments(params, signal),
    placeholderData: keepPreviousData,
    enabled,
  })
}
