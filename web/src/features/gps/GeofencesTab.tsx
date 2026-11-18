import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../shared/api/errors'
import { codecs, useUrlState } from '../../shared/hooks/useUrlState'
import { Badge } from '../../shared/ui/Badge'
import { Button } from '../../shared/ui/Button'
import { Checkbox } from '../../shared/ui/Checkbox'
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { Drawer } from '../../shared/ui/Drawer'
import { EmptyState } from '../../shared/ui/EmptyState'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { FormBanner } from '../../shared/ui/FormBanner'
import { PAGE_SIZES, Pagination } from '../../shared/ui/Pagination'
import { Select } from '../../shared/ui/Select'
import { TextArea, TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { Plus, Trash2 } from '../../shared/ui/icons'
import { useDeleteGeofence, useGeofences, useSaveGeofence } from './hooks'
import { GEOFENCE_KINDS, type Geofence } from './types'

const SCHEMA = { q: codecs.string(''), page: codecs.positiveInt(1), pageSize: codecs.choiceInt(PAGE_SIZES, 50) }

/** Контур из текста: по строке «широта, долгота». */
export function parsePolygon(text: string): [number, number][] | null {
  const points: [number, number][] = []
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    const parts = line.split(/[;,\s]+/).filter(Boolean).map((x) => Number(x.replace(',', '.')))
    const [lat, lon] = parts
    if (parts.length !== 2 || lat === undefined || lon === undefined || !Number.isFinite(lat) || !Number.isFinite(lon)) return null
    points.push([lat, lon])
  }
  return points.length >= 3 ? points : null
}

function GeofenceDrawer({ geofence, onClose }: { geofence: Geofence | null; onClose: () => void }) {
  const { t } = useTranslation()
  const save = useSaveGeofence()
  const [error, setError] = useState<string>()
  const [form, setForm] = useState({
    name: geofence?.name ?? '',
    kind: (geofence?.kind ?? 'other'),
    shape: (geofence?.shape ?? 'circle'),
    lat: geofence?.lat ?? '',
    lon: geofence?.lon ?? '',
    radius: String(geofence?.radius_m ?? 500),
    polygon: geofence?.polygon?.map((p) => `${String(p[0])}, ${String(p[1])}`).join('\n') ?? '',
    is_active: geofence?.is_active ?? true,
  })
  const wialon = geofence?.source === 'wialon'
  const submit = () => {
    setError(undefined)
    if (!form.name.trim()) { setError(`${t('gps.geoName')}: ${t('errors.requiredField')}`); return }
    const base = { name: form.name.trim(), kind: form.kind, is_active: form.is_active }
    let body
    if (form.shape === 'polygon') {
      const polygon = parsePolygon(form.polygon)
      if (!polygon) { setError(t('gps.polygonInvalid')); return }
      body = { ...base, shape: 'polygon' as const, polygon }
    } else {
      const lat = Number(form.lat.replace(',', '.'))
      const lon = Number(form.lon.replace(',', '.'))
      const radius = Number(form.radius)
      if (!form.lat || !form.lon || !Number.isFinite(lat) || !Number.isFinite(lon)) { setError(t('gps.coordsInvalid')); return }
      body = { ...base, shape: 'circle' as const, lat, lon, radius_m: radius, polygon: null }
    }
    save.mutate({ id: geofence?.id ?? null, body }, { onSuccess: onClose, onError: (e) => { setError(errorMessage(e, t)) } })
  }
  return (
    <Drawer
      open
      title={geofence ? geofence.name : t('gps.geoNew')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <Button variant="primary" onClick={submit} disabled={save.isPending}>{save.isPending ? t('common.saving') : t('common.save')}</Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormBanner message={error} />
        {wialon ? <p className="text-sm text-muted">{t('gps.geoFromWialon')}</p> : null}
        <TextField label={t('gps.geoName')} required value={form.name} disabled={wialon} onChange={(e) => { setForm({ ...form, name: e.target.value }) }} />
        <Select label={t('gps.geoKind')} value={form.kind} options={GEOFENCE_KINDS.map((k) => ({ value: k, label: t(`gps.kinds.${k}`) }))} onChange={(v) => { setForm({ ...form, kind: GEOFENCE_KINDS.find((k) => k === v) ?? 'other' }) }} />
        {!wialon ? (
          <Select label={t('gps.geoShape')} value={form.shape} options={[{ value: 'circle', label: t('gps.shapes.circle') }, { value: 'polygon', label: t('gps.shapes.polygon') }]} onChange={(v) => { setForm({ ...form, shape: v === 'polygon' ? 'polygon' : 'circle' }) }} />
        ) : null}
        {form.shape === 'circle' && !wialon ? (
          <div className="grid grid-cols-3 gap-3">
            <TextField label={t('gps.lat')} inputMode="decimal" value={form.lat} onChange={(e) => { setForm({ ...form, lat: e.target.value }) }} />
            <TextField label={t('gps.lon')} inputMode="decimal" value={form.lon} onChange={(e) => { setForm({ ...form, lon: e.target.value }) }} />
            <TextField label={t('gps.radius')} inputMode="numeric" value={form.radius} onChange={(e) => { setForm({ ...form, radius: e.target.value.replace(/\D/g, '') }) }} />
          </div>
        ) : null}
        {form.shape === 'polygon' && !wialon ? (
          <TextArea label={t('gps.polygon')} hint={t('gps.polygonHint')} rows={6} value={form.polygon} onChange={(e) => { setForm({ ...form, polygon: e.target.value }) }} />
        ) : null}
        <Checkbox label={t('gps.geoActive')} checked={form.is_active} onChange={(e) => { setForm({ ...form, is_active: e.target.checked }) }} />
      </div>
    </Drawer>
  )
}

/** Геозоны: зоны из Wialon (контур или круг) и свои круги и контуры; вкл/выкл и тип зоны задаёт офис. */
export function GeofencesTab() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA, { pageKey: 'page' })
  const list = useGeofences(state.page, state.q)
  const remove = useDeleteGeofence()
  const [editor, setEditor] = useState<{ geofence: Geofence | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<Geofence | null>(null)
  const columns: Column<Geofence>[] = [
    {
      key: 'name',
      header: t('gps.geoName'),
      cell: (g) => (
        <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setEditor({ geofence: g, nonce: Date.now() }) }}>{g.name}</button>
      ),
    },
    { key: 'kind', header: t('gps.geoKind'), cell: (g) => t(`gps.kinds.${g.kind}`) },
    { key: 'shape', header: t('gps.geoShape'), cell: (g) => (g.shape === 'polygon' ? `${t('gps.shapes.polygon')} (${String(g.polygon?.length ?? 0)})` : `${t('gps.shapes.circle')} ${String(g.radius_m)} ${t('gps.m')}`) },
    { key: 'source', header: t('gps.source'), cell: (g) => (g.source === 'wialon' ? 'Wialon' : t('gps.manual')) },
    { key: 'status', header: t('common.status'), cell: (g) => <span className="flex flex-wrap gap-1"><Badge tone={g.is_active ? 'success' : 'neutral'}>{g.is_active ? t('gps.active') : t('gps.inactive')}</Badge>{g.is_approximate ? <Badge tone="warning">{t('gps.approximate')}</Badge> : null}</span> },
    { key: 'actions', header: <span className="sr-only">{t('common.actions')}</span>, align: 'right', cell: (g) => <WriteButton permission="gps.manage" variant="dangerSoft" className="h-8! px-2.5! text-xs!" icon={Trash2} aria-label={t('gps.geoDelete', { name: g.name })} onClick={() => { setToDelete(g) }}>{t('common.delete')}</WriteButton> },
  ]
  return (
    <div className="space-y-3">
      <FilterBar
        search={<FilterItem className="w-auto"> <TextField label={t('common.search')} type="search" placeholder={t('gps.searchGeofences')} value={state.q} onChange={(e) => { setState({ q: e.target.value }, { replace: true }) }} /> </FilterItem>}
        canReset={state.q !== ''}
        onReset={() => { setState({ q: '' }) }}
        actions={<WriteButton permission="gps.manage" variant="primary" icon={Plus} onClick={() => { setEditor({ geofence: null, nonce: Date.now() }) }}>{t('gps.geoNew')}</WriteButton>}
      />
      <DataTable
        onRowClick={(g) => { setEditor({ geofence: g, nonce: Date.now() }) }}
        caption={t('gps.tabs.geofences')}
        columns={columns}
        rows={list.data?.results}
        rowKey={(g) => g.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={t('gps.geoEmpty')} hint={t('gps.geoEmptyHint')} />}
      />
      <Pagination page={state.page} pageSize={state.pageSize} count={list.data?.count ?? 0} onPage={(page) => { setState({ page }) }} onPageSize={(pageSize) => { setState({ pageSize }) }} />
      {editor ? <GeofenceDrawer key={editor.nonce} geofence={editor.geofence} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('gps.geoDeleteTitle')}
        message={t('gps.geoDeleteMessage', { name: toDelete?.name ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onCancel={() => { setToDelete(null); remove.reset() }}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id, { onSuccess: () => { setToDelete(null) } }) }}
      />
    </div>
  )
}
