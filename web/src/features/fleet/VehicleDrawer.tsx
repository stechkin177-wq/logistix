import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useCanWrite } from '../../shared/auth/useCanWrite'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../shared/forms/useFocusInvalid'
import { Badge } from '../../shared/ui/Badge'
import { Button } from '../../shared/ui/Button'
import { Checkbox } from '../../shared/ui/Checkbox'
import { Drawer } from '../../shared/ui/Drawer'
import { FormBanner } from '../../shared/ui/FormBanner'
import { Select } from '../../shared/ui/Select'
import { Tabs } from '../../shared/ui/Tabs'
import { TextArea, TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { IssueDocumentButton } from '../documents/IssueDocumentButton'
import { ChildTab, type FieldDef } from './ChildTab'
import { useFuelStats, useMileageCheck, useSaveVehicle } from './hooks'
import { VEHICLE_KINDS, VEHICLE_STATUSES, type Vehicle, type VehicleKind, type VehicleStatus } from './types'

type TabKey = 'main' | 'documents' | 'insurance' | 'service' | 'fuel' | 'history'
const TAB_KEYS: TabKey[] = ['main', 'documents', 'insurance', 'service', 'fuel', 'history']
const KNOWN = /^(kind|plate|vin|make|model|year|body_type|capacity_kg|volume_m3|status|gps_check|notes)$/

interface FormState {
  kind: VehicleKind
  plate: string
  vin: string
  make: string
  model: string
  year: string
  body_type: string
  capacity_kg: string
  volume_m3: string
  status: VehicleStatus
  gps_check: boolean
  notes: string
}

const initial = (v: Vehicle | null): FormState => ({
  kind: v?.kind ?? 'truck',
  plate: v?.plate ?? '',
  vin: v?.vin ?? '',
  make: v?.make ?? '',
  model: v?.model ?? '',
  year: v?.year != null ? String(v.year) : '',
  body_type: v?.body_type ?? '',
  capacity_kg: v?.capacity_kg != null ? String(v.capacity_kg) : '',
  volume_m3: v?.volume_m3 ?? '',
  status: v?.status ?? 'active',
  gps_check: v?.gps_check ?? false,
  notes: v?.notes ?? '',
})

/** Единая карточка техники: основное, документы, страхование, обслуживание, заправки, пробег. */
export function VehicleDrawer({ vehicle, onClose }: { vehicle: Vehicle | null; onClose: () => void }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState<TabKey>('main')
  const tabs = TAB_KEYS.map((key) => ({ key, label: t(`fleet.tabs.${key}`), disabled: vehicle === null && key !== 'main' }))
  return (
    <Drawer open title={vehicle ? vehicle.plate : t('fleet.new')} onClose={onClose} width="max-w-2xl">
      <Tabs label={t('fleet.tabsLabel')} tabs={tabs} active={tab} onChange={(k) => { setTab(k as TabKey) }} />
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="mt-3">
        {tab === 'main' ? <MainTab vehicle={vehicle} onClose={onClose} /> : null}
        {vehicle && tab !== 'main' ? <VehicleTab tab={tab} vehicle={vehicle} /> : null}
      </div>
    </Drawer>
  )
}

function MainTab({ vehicle, onClose }: { vehicle: Vehicle | null; onClose: () => void }) {
  const { t } = useTranslation()
  const [form, setForm] = useState(() => initial(vehicle))
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const formRef = useRef<HTMLFormElement>(null)
  const save = useSaveVehicle()
  const permission = vehicle ? 'fleet.update' : 'fleet.create'
  const canSave = useCanWrite(permission)
  useFocusInvalid(formRef, errors)
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => { setForm((f) => ({ ...f, [key]: value })) }

  const submit = () => {
    if (!form.plate.trim()) { setErrors({ fields: { plate: t('errors.requiredField') }, banner: undefined }); return }
    setErrors(NO_ERRORS)
    save.mutate(
      {
        id: vehicle?.id ?? null,
        body: {
          ...form,
          plate: form.plate.trim(),
          year: form.year ? Number(form.year) : null,
          capacity_kg: form.capacity_kg ? Number(form.capacity_kg) : null,
          volume_m3: form.volume_m3 || null,
        },
      },
      { onSuccess: onClose, onError: (e) => { setErrors(serverErrors(e, t, (p) => KNOWN.test(p))) } },
    )
  }

  const f = errors.fields
  return (
    <form ref={formRef} className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit() }}>
      <FormBanner message={errors.banner} />
      <div className="grid grid-cols-2 gap-3">
        <Select label={t('fleet.kind')} value={form.kind} options={VEHICLE_KINDS.map((k) => ({ value: k, label: t(`fleet.kinds.${k}`) }))} onChange={(v) => { set('kind', v as VehicleKind) }} />
        <TextField label={t('fleet.plate')} required value={form.plate} error={f.plate} onChange={(e) => { set('plate', e.target.value) }} />
        <TextField label={t('fleet.make')} value={form.make} error={f.make} onChange={(e) => { set('make', e.target.value) }} />
        <TextField label={t('fleet.model')} value={form.model} error={f.model} onChange={(e) => { set('model', e.target.value) }} />
        <TextField label={t('fleet.year')} inputMode="numeric" value={form.year} error={f.year} onChange={(e) => { set('year', e.target.value) }} />
        <TextField label={t('fleet.vin')} value={form.vin} error={f.vin} onChange={(e) => { set('vin', e.target.value) }} />
        <TextField label={t('fleet.bodyType')} value={form.body_type} error={f.body_type} onChange={(e) => { set('body_type', e.target.value) }} />
        <TextField label={t('fleet.capacityKg')} inputMode="numeric" value={form.capacity_kg} error={f.capacity_kg} onChange={(e) => { set('capacity_kg', e.target.value) }} />
        <TextField label={t('fleet.volumeM3')} inputMode="decimal" value={form.volume_m3} error={f.volume_m3} onChange={(e) => { set('volume_m3', e.target.value) }} />
        <Select label={t('common.status')} value={form.status} options={VEHICLE_STATUSES.map((s) => ({ value: s, label: t(`fleet.status.${s}`) }))} onChange={(v) => { set('status', v as VehicleStatus) }} />
        <Checkbox label={t('fleet.gpsCheck')} checked={form.gps_check} onChange={(e) => { set('gps_check', e.target.checked) }} />
        <TextArea fieldClassName="col-span-2" label={t('common.comment')} value={form.notes} error={f.notes} onChange={(e) => { set('notes', e.target.value) }} />
      </div>
      {vehicle?.gps_check ? <MileageCheckBlock id={vehicle.id} /> : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        {vehicle ? <IssueDocumentButton kind="letter" module="fleet" source={{ subject_type: 'fleet.vehicle', subject_id: vehicle.id }} label={t('fleet.issueCertificate')} /> : <span />}
        <div className="flex gap-2">
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission={permission} variant="primary" onClick={submit} disabled={save.isPending || !canSave}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </div>
      </div>
    </form>
  )
}

/** Сверка пробега: официальный, по GPS и разница. Только показ, ничего не изменяет. */
function MileageCheckBlock({ id }: { id: number }) {
  const { t } = useTranslation()
  const check = useMileageCheck(id, true)
  const d = check.data
  if (!d?.enabled) return null
  return (
    <section aria-label={t('fleet.mileageCheck')} className="rounded border border-slate-200 p-2 text-sm dark:border-slate-700">
      <div className="font-medium">{t('fleet.mileageCheck')}</div>
      <div>{t('fleet.officialKm')}: {d.official_km ?? '—'}</div>
      {d.gps_available ? (
        <>
          <div>{t('fleet.gpsKm')}: {d.gps_km}</div>
          <div>{t('fleet.differenceKm')}: {d.difference_km ?? '—'}</div>
          {d.warning ? <Badge tone="danger">{t('fleet.mileageMismatch', { km: d.threshold_km })}</Badge> : null}
        </>
      ) : (
        <div className="text-slate-500">{t('fleet.gpsUnavailable')}</div>
      )}
    </section>
  )
}

function VehicleTab({ tab, vehicle }: { tab: Exclude<TabKey, 'main'>; vehicle: Vehicle }) {
  const { t } = useTranslation()
  const sel = (prefix: string, keys: readonly string[]) => keys.map((k) => ({ value: k, label: t(`${prefix}.${k}`) }))
  const str = (v: unknown) => (typeof v === 'string' || typeof v === 'number' ? String(v) : '')
  const date = (label: string, key: string): FieldDef => ({ key, label, type: 'date' })

  if (tab === 'documents') {
    return (
      <ChildTab
        path="vehicle-documents"
        vehicle={vehicle.id}
        emptyText={t('fleet.noDocuments')}
        fields={[
          { key: 'kind', label: t('fleet.docType'), type: 'select', options: sel('fleet.docKind', ['registration', 'inspection', 'permit', 'other']) },
          { key: 'number', label: t('fleet.number'), type: 'text' },
          date(t('fleet.expiresAt'), 'expires_at'),
        ]}
        summary={(r) => `${t(`fleet.docKind.${str(r.kind)}`)} ${str(r.number)}${r.expires_at ? ` · ${t('fleet.until')} ${str(r.expires_at)}` : ''}`}
      />
    )
  }
  if (tab === 'insurance') {
    return (
      <ChildTab
        path="insurances"
        vehicle={vehicle.id}
        emptyText={t('fleet.noInsurances')}
        fields={[
          { key: 'kind', label: t('fleet.insuranceType'), type: 'select', options: sel('fleet.insKind', ['osago', 'kasko', 'cargo', 'other']) },
          { key: 'policy_number', label: t('fleet.policyNumber'), type: 'text' },
          { key: 'insurer', label: t('fleet.insurer'), type: 'text' },
          date(t('fleet.expiresAt'), 'expires_at'),
        ]}
        summary={(r) => `${t(`fleet.insKind.${str(r.kind)}`)} ${str(r.policy_number)}${r.expires_at ? ` · ${t('fleet.until')} ${str(r.expires_at)}` : ''}`}
      />
    )
  }
  if (tab === 'service') {
    return (
      <ChildTab
        path="service-records"
        vehicle={vehicle.id}
        emptyText={t('fleet.noServices')}
        fields={[
          { key: 'kind', label: t('fleet.serviceType'), type: 'select', options: sel('fleet.serviceKind', ['maintenance', 'repair', 'tires', 'oil', 'filters', 'inspection', 'other']) },
          { key: 'title', label: t('fleet.serviceTitle'), type: 'text', required: true },
          { key: 'status', label: t('common.status'), type: 'select', options: sel('fleet.serviceStatus', ['planned', 'in_progress', 'done', 'cancelled']) },
          date(t('fleet.plannedDate'), 'planned_date'),
          date(t('fleet.doneDate'), 'done_date'),
          { key: 'odometer_km', label: t('fleet.referenceKm'), type: 'number' },
          date(t('fleet.nextDueDate'), 'next_due_date'),
          { key: 'next_due_km', label: t('fleet.nextDueKm'), type: 'number' },
        ]}
        summary={(r) => `${t(`fleet.serviceKind.${str(r.kind)}`)}: ${str(r.title)} · ${t(`fleet.serviceStatus.${str(r.status)}`)}${r.done_date ? ` · ${str(r.done_date)}` : ''}`}
      />
    )
  }
  if (tab === 'fuel') return <FuelTab vehicle={vehicle} />
  return (
    <ChildTab
      path="mileage"
      vehicle={vehicle.id}
      readOnly
      emptyText={t('fleet.noMileage')}
      header={<p className="text-sm text-slate-500">{t('fleet.mileageHint')}</p>}
      fields={[]}
      summary={(r) => `${str(r.recorded_at).slice(0, 10)} · ${t(`fleet.mileageSource.${str(r.source)}`)} · ${str(r.odometer_km)} ${t('fleet.km')}`}
    />
  )
}

function FuelTab({ vehicle }: { vehicle: Vehicle }) {
  const { t } = useTranslation()
  const stats = useFuelStats(vehicle.id)
  const avg = stats.data?.average_l_per_100km
  return (
    <ChildTab
      path="fuel-fills"
      vehicle={vehicle.id}
      emptyText={t('fleet.noFuel')}
      header={
        <p className="text-sm">
          {t('fleet.averageConsumption')}: <b>{avg ? `${avg} ${t('fleet.lPer100')}` : t('fleet.notEnoughData')}</b>
        </p>
      }
      fields={[
        { key: 'filled_at', label: t('fleet.filledAt'), type: 'datetime', required: true },
        { key: 'liters', label: t('fleet.liters'), type: 'number', required: true },
        { key: 'odometer_km', label: t('fleet.referenceKm'), type: 'number' },
        { key: 'full_tank', label: t('fleet.fullTank'), type: 'checkbox', initial: true },
      ]}
      summary={(r) => `${String(r.filled_at).slice(0, 16).replace('T', ' ')} · ${String(r.liters)} ${t('fleet.l')}${typeof r.odometer_km === 'number' ? ` · ${String(r.odometer_km)} ${t('fleet.km')}` : ''}${r.full_tank ? '' : ` · ${t('fleet.partial')}`}`}
    />
  )
}
