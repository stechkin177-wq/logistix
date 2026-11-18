export interface GpsAccount {
  configured: boolean
  has_token?: boolean
  base_url?: string
  is_active?: boolean
  last_synced_at?: string | null
  last_sync_error?: string
  webhook_path?: string
}
export interface GpsAccountForm { token: string; base_url: string; is_active: boolean }

export interface GpsUnit {
  id: number
  unit_id: string
  name: string
  vehicle: number | null
  vehicle_plate: string | null
  lat: string | null
  lon: string | null
  speed_kmh: number | null
  position_at: string | null
  location_text: string
  odometer_km: string | null
  odometer_at: string | null
  fuel_level_l: string | null
  fuel_level_at: string | null
  seen_at: string | null
}

export const GEOFENCE_KINDS = ['warehouse', 'border', 'city', 'client', 'other'] as const
export type GeofenceKind = (typeof GEOFENCE_KINDS)[number]
export type GeofenceShape = 'circle' | 'polygon'

export interface Geofence {
  id: number
  name: string
  kind: GeofenceKind
  shape: GeofenceShape
  lat: string
  lon: string
  radius_m: number
  polygon: [number, number][] | null
  is_active: boolean
  source: 'manual' | 'wialon'
  is_approximate: boolean
}
export interface GeofencePayload {
  name: string
  kind: GeofenceKind
  shape: GeofenceShape
  lat?: number
  lon?: number
  radius_m?: number
  polygon?: [number, number][] | null
  is_active: boolean
}

export interface GeofenceEvent {
  id: number
  geofence: number
  geofence_name: string
  vehicle: number
  vehicle_plate: string
  event_type: 'enter' | 'exit'
  occurred_at: string
}

export interface SyncResult {
  ok: boolean
  error?: string
  units?: { units_seen: number; created: number; updated: number; auto_linked: number }
  geofences?: { zones_seen: number; created: number; updated: number; deactivated: number }
}

export interface TrackPoint { t: string; lat: number; lon: number; speed: number | null }
export interface TrackResult {
  available: boolean
  reason: '' | 'no_account' | 'wialon_error'
  points: TrackPoint[]
  total_points: number
  length_km: number | null
}
