import 'leaflet/dist/leaflet.css'
import L from 'leaflet'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { Geofence, GpsUnit, TrackPoint } from './types'

const TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
const ALMATY: L.LatLngTuple = [43.238949, 76.889709]

interface Props {
  units: GpsUnit[]
  geofences: Geofence[]
  track: TrackPoint[]
  selectedUnit: number | null
  onSelectUnit: (id: number) => void
}

/** Карта OpenStreetMap: техника на связи, геозоны (круги и контуры) и трек выбранного юнита. */
export default function GpsMap({ units, geofences, track, selectedUnit, onSelectUnit }: Props) {
  const { t } = useTranslation()
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layers = useRef<L.LayerGroup | null>(null)
  const fitted = useRef(false)

  useEffect(() => {
    if (!box.current) return
    const instance = L.map(box.current, { center: ALMATY, zoom: 5, scrollWheelZoom: true })
    // OSM требует Referer: плитки грузятся с referrerPolicy "origin" (общий заголовок сайта его не отдаёт)
    L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 18, referrerPolicy: 'origin' }).addTo(instance)
    layers.current = L.layerGroup().addTo(instance)
    map.current = instance
    return () => { instance.remove(); map.current = null; layers.current = null; fitted.current = false }
  }, [])

  useEffect(() => {
    const group = layers.current
    const instance = map.current
    if (!group || !instance) return
    group.clearLayers()
    const bounds: L.LatLngTuple[] = []
    for (const g of geofences) {
      if (!g.is_active) continue
      const style = { color: g.source === 'wialon' ? '#7c3aed' : '#0891b2', weight: 1.5, fillOpacity: 0.12 }
      const shape = g.shape === 'polygon' && g.polygon
        ? L.polygon(g.polygon, style)
        : L.circle([Number(g.lat), Number(g.lon)], { ...style, radius: g.radius_m })
      shape.bindTooltip(g.name).addTo(group)
    }
    for (const u of units) {
      if (!u.lat || !u.lon) continue
      const pos: L.LatLngTuple = [Number(u.lat), Number(u.lon)]
      const active = u.id === selectedUnit
      L.circleMarker(pos, { radius: active ? 9 : 6, color: '#ffffff', weight: 2, fillColor: u.vehicle !== null ? '#2563eb' : '#64748b', fillOpacity: 1 })
        .bindTooltip(`${u.vehicle_plate ?? u.name}${u.speed_kmh ? `, ${String(u.speed_kmh)} ${t('gps.kmh')}` : ''}`)
        .on('click', () => { onSelectUnit(u.id) })
        .addTo(group)
      bounds.push(pos)
    }
    if (track.length > 1) {
      const line: L.LatLngTuple[] = track.map((p) => [p.lat, p.lon])
      L.polyline(line, { color: '#dc2626', weight: 4, opacity: 0.85 }).addTo(group)
      const first = line[0]
      const last = line[line.length - 1]
      if (first) L.circleMarker(first, { radius: 6, color: '#ffffff', weight: 2, fillColor: '#16a34a', fillOpacity: 1 }).bindTooltip(t('gps.trackStart')).addTo(group)
      if (last) L.circleMarker(last, { radius: 6, color: '#ffffff', weight: 2, fillColor: '#dc2626', fillOpacity: 1 }).bindTooltip(t('gps.trackEnd')).addTo(group)
      instance.fitBounds(L.latLngBounds(line), { padding: [30, 30] })
      fitted.current = true
    } else if (!fitted.current && bounds.length > 0) {
      instance.fitBounds(L.latLngBounds(bounds), { padding: [40, 40], maxZoom: 12 })
      fitted.current = true
    }
  }, [units, geofences, track, selectedUnit, onSelectUnit, t])

  return <div ref={box} role="region" aria-label={t('gps.mapLabel')} className="h-[26rem] w-full overflow-hidden rounded-card border border-line md:h-[34rem]" />
}
