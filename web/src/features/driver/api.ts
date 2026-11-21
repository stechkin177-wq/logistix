import { api } from '../../shared/api/client'
import type { OcrDocType, OcrDocument } from '../ocr/types'
import type { DriverAction, DriverMe, DriverScope, DriverTrip, DriverTripDetail } from './types'

export const getDriverMe = (signal?: AbortSignal) => api.get<DriverMe>('/driver/me/', undefined, { signal })
export const listDriverTrips = (scope: DriverScope, signal?: AbortSignal) =>
  api.get<{ results: DriverTrip[] }>('/driver/trips/', { scope }, { signal })
export const getDriverTrip = (id: number, signal?: AbortSignal) => api.get<DriverTripDetail>(`/driver/trips/${String(id)}/`, undefined, { signal })
export const doTripAction = (id: number, body: { action: DriverAction; vehicle_km?: number; engine_hours?: number }) =>
  api.post<DriverTripDetail>(`/driver/trips/${String(id)}/action/`, body)

export const listDriverReports = (archived: boolean, signal?: AbortSignal) =>
  api.get<{ results: OcrDocument[] }>('/driver/reports/', { archived: archived ? 'true' : undefined }, { signal })
export const listDriverReportTypes = (signal?: AbortSignal) =>
  api.get<{ results: { code: string; name: string; handler: string }[] }>('/driver/report-types/', undefined, { signal })
export const archiveDriverReport = (id: number, archived: boolean) => api.post<OcrDocument>(`/driver/reports/${String(id)}/archive/`, { archived })
export const getDriverReportImage = async (id: number) => (await api.download(`/driver/reports/${String(id)}/image/`)).blob
export const sendDriverReport = (file: Blob, name: string, docType: OcrDocType, trip: number | null) => {
  const form = new FormData()
  form.append('file', file, name)
  form.append('doc_type', docType)
  if (trip !== null) form.append('trip', String(trip))
  return api.upload<OcrDocument>('/driver/reports/', form)
}
