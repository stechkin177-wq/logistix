import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useCanWrite } from '../../shared/auth/useCanWrite'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../shared/forms/useFocusInvalid'
import { Button } from '../../shared/ui/Button'
import { DateInput } from '../../shared/ui/DateInput'
import { Drawer } from '../../shared/ui/Drawer'
import { FormBanner } from '../../shared/ui/FormBanner'
import { Select } from '../../shared/ui/Select'
import { TextArea, TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { IssueDocumentButton } from '../documents/IssueDocumentButton'
import { TypedDocumentForm, documentSummary } from '../doctypes/TypedDocumentForm'
import { useAddDriverDocument, useDeleteDriverDocument, useSaveDriver } from './hooks'
import { DRIVER_STATUSES, type Driver, type DriverStatus } from './types'

const IIN_RE = /^\d{12}$/

interface FormState {
  full_name: string
  phone: string
  iin: string
  license_number: string
  license_categories: string
  license_expires: string
  status: DriverStatus
  notes: string
}

const initial = (d: Driver | null): FormState => ({
  full_name: d?.full_name ?? '',
  phone: d?.phone ?? '',
  iin: d?.iin ?? '',
  license_number: d?.license_number ?? '',
  license_categories: d?.license_categories ?? '',
  license_expires: d?.license_expires ?? '',
  status: d?.status ?? 'active',
  notes: d?.notes ?? '',
})

const KNOWN = /^(full_name|phone|iin|license_number|license_categories|license_expires|status|notes)$/

/** Карточка водителя: основное, документы водителя и справка (через общую систему документов). */
export function DriverDrawer({ driver, onClose }: { driver: Driver | null; onClose: () => void }) {
  const { t } = useTranslation()
  const [form, setForm] = useState(() => initial(driver))
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const formRef = useRef<HTMLFormElement>(null)
  const save = useSaveDriver()
  const editing = driver !== null
  const permission = editing ? 'drivers.update' : 'drivers.create'
  const canSave = useCanWrite(permission)
  useFocusInvalid(formRef, errors)
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => { setForm((f) => ({ ...f, [key]: value })) }

  const submit = () => {
    const local: Record<string, string> = {}
    if (!form.full_name.trim()) local.full_name = t('errors.requiredField')
    if (form.iin.trim() && !IIN_RE.test(form.iin.trim())) local.iin = t('drivers.iinHint')
    if (Object.keys(local).length > 0) { setErrors({ fields: local, banner: undefined }); return }
    setErrors(NO_ERRORS)
    save.mutate(
      {
        id: driver?.id ?? null,
        body: {
          ...form,
          full_name: form.full_name.trim(),
          iin: form.iin.trim(),
          license_expires: form.license_expires || null,
        },
      },
      { onSuccess: onClose, onError: (e) => { setErrors(serverErrors(e, t, (p) => KNOWN.test(p))) } },
    )
  }

  const f = errors.fields
  return (
    <Drawer
      open
      title={editing ? t('drivers.edit') : t('drivers.new')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission={permission} variant="primary" onClick={submit} disabled={save.isPending || !canSave}>
            {save.isPending ? t('common.saving') : t('common.save')}
          </WriteButton>
        </>
      }
    >
      <form ref={formRef} className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <FormBanner message={errors.banner} />
        <div className="grid grid-cols-2 gap-3">
          <TextField fieldClassName="col-span-2" label={t('drivers.fullName')} required value={form.full_name} error={f.full_name} onChange={(e) => { set('full_name', e.target.value) }} />
          <TextField label={t('drivers.phone')} value={form.phone} error={f.phone} onChange={(e) => { set('phone', e.target.value) }} />
          <TextField label={t('drivers.iin')} inputMode="numeric" value={form.iin} error={f.iin} onChange={(e) => { set('iin', e.target.value) }} />
          <TextField label={t('drivers.licenseNumber')} value={form.license_number} error={f.license_number} onChange={(e) => { set('license_number', e.target.value) }} />
          <TextField label={t('drivers.licenseCategories')} value={form.license_categories} error={f.license_categories} onChange={(e) => { set('license_categories', e.target.value) }} />
          <DateInput label={t('drivers.licenseExpires')} value={form.license_expires} error={f.license_expires} onChange={(v) => { set('license_expires', v) }} />
          <Select
            label={t('common.status')}
            value={form.status}
            options={DRIVER_STATUSES.map((s) => ({ value: s, label: t(`drivers.status.${s}`) }))}
            onChange={(v) => { set('status', v as DriverStatus) }}
          />
          <TextArea fieldClassName="col-span-2" label={t('common.comment')} value={form.notes} error={f.notes} onChange={(e) => { set('notes', e.target.value) }} />
        </div>
      </form>
      {driver ? (
        <>
          <div className="mt-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold">{t('drivers.documents')}</h3>
            <IssueDocumentButton
              kind="letter"
              module="drivers"
              source={{ subject_type: 'drivers.driver', subject_id: driver.id }}
              label={t('drivers.issueCertificate')}
            />
          </div>
          <DocumentsBlock driver={driver} />
        </>
      ) : null}
    </Drawer>
  )
}

function DocumentsBlock({ driver }: { driver: Driver }) {
  const { t } = useTranslation()
  const add = useAddDriverDocument()
  const remove = useDeleteDriverDocument()

  return (
    <div className="mt-2 space-y-2">
      {driver.documents.length === 0 ? <p className="text-sm text-muted">{t('drivers.noDocuments')}</p> : null}
      <ul className="divide-y divide-slate-200 text-sm">
        {driver.documents.map((d) => (
          <li key={d.id} className="flex items-center justify-between gap-2 py-1.5">
            <span>{documentSummary(d, t(`drivers.docKind.${d.kind}`), t('drivers.until'))}</span>
            <WriteButton permission="drivers.update" variant="ghost" aria-label={t('drivers.deleteDocument')} onClick={() => { remove.mutate(d.id) }}>
              {t('common.delete')}
            </WriteButton>
          </li>
        ))}
      </ul>
      <TypedDocumentForm subject="driver" issuedKey="issued_at" permission="drivers.update" owner={{ driver: driver.id }} create={add} addLabel={t('drivers.addDocument')} />
    </div>
  )
}
