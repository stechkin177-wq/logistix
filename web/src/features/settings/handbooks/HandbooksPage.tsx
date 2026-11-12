import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../../shared/api/client'
import { errorMessage } from '../../../shared/api/errors'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { useSession } from '../../../shared/auth/useSession'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import type { HandbookDetail, HandbookValue } from '../../../shared/api/types'
import { Badge } from '../../../shared/ui/Badge'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { Checkbox } from '../../../shared/ui/Checkbox'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { Drawer } from '../../../shared/ui/Drawer'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { Spinner } from '../../../shared/ui/Spinner'
import { TextField } from '../../../shared/ui/TextField'
import { pushToast } from '../../../shared/ui/toast'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { PageHeader } from '../../../shared/ui/PageHeader'
import { BookOpen } from '../../../shared/ui/icons'

interface HandbookSummary { code: string; name: string; group: string; values_count: number }

/** Справочники со статусами: у них есть «начальное» значение. */
const STATUS_HANDBOOKS = ['order_status', 'consignment_status', 'trip_status']

function useInvalidateHandbooks() {
  const qc = useQueryClient()
  return () => Promise.all([qc.invalidateQueries({ queryKey: ['handbooks'] }), qc.invalidateQueries({ queryKey: ['handbook-list'] })])
}

interface FormState { name: string; code: string; order: string; is_initial: boolean; is_final: boolean; is_active: boolean }

function ValueDrawer({ handbook, value, onClose }: { handbook: HandbookDetail; value: HandbookValue | null; onClose: () => void }) {
  const { t } = useTranslation()
  const invalidate = useInvalidateHandbooks()
  const editing = value !== null
  const permission = editing ? 'handbooks.update' : 'handbooks.create'
  const canSave = useCanWrite(permission)
  const isStatus = STATUS_HANDBOOKS.includes(handbook.code)
  const isSystem = value?.is_system ?? false
  const [form, setForm] = useState<FormState>({
    name: value?.name ?? '',
    code: value?.code ?? '',
    order: value ? String(value.order) : '',
    is_initial: value?.is_initial ?? false,
    is_final: value?.is_final ?? false,
    is_active: value?.is_active ?? true,
  })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const ref = useRef<HTMLFormElement>(null)
  useFocusInvalid(ref, errors)
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      value ? api.patch<HandbookValue>(`/handbook-values/${String(value.id)}/`, body) : api.post<HandbookValue>('/handbook-values/', { handbook: handbook.code, ...body }),
    onSuccess: async () => { await invalidate(); onClose() },
    onError: (error) => { setErrors(serverErrors(error, t, (p) => ['name', 'code', 'order', 'is_initial', 'is_final', 'is_active', 'handbook'].includes(p))) },
  })
  const submit = () => {
    const local: Record<string, string> = {}
    if (!form.name.trim()) local.name = t('errors.requiredField')
    if (form.order.trim() && !/^\d{1,9}$/.test(form.order.trim())) local.order = t('errors.invalidNumber')
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    // у системного значения код, «конечное» и «активно» не отправляются: сервер их защищает
    save.mutate({
      name: form.name.trim(),
      ...(isSystem ? {} : { code: form.code.trim(), is_final: form.is_final, is_active: form.is_active }),
      ...(form.order.trim() ? { order: Number(form.order) } : {}),
      ...(isStatus && !isSystem ? { is_initial: form.is_initial } : {}),
    })
  }
  const f = errors.fields
  return (
    <Drawer
      open
      title={value ? t('handbooks.editValue') : t('handbooks.newValue', { name: handbook.name })}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission={permission} variant="primary" onClick={submit} disabled={save.isPending}>{save.isPending ? t('common.saving') : t('common.save')}</WriteButton>
        </>
      }
    >
      <form ref={ref} noValidate className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (canSave) submit() }}>
        <FormBanner message={errors.banner} />
        <TextField label={t('handbooks.name')} required value={form.name} error={f.name} onChange={(e) => { setForm((s) => ({ ...s, name: e.target.value })) }} />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <TextField label={t('handbooks.code')} value={form.code} error={f.code} disabled={isSystem} hint={isSystem ? t('handbooks.systemHint') : t('handbooks.codeHint')} onChange={(e) => { setForm((s) => ({ ...s, code: e.target.value })) }} />
          <TextField label={t('handbooks.order')} inputMode="numeric" value={form.order} error={f.order} hint={editing ? undefined : t('handbooks.orderHint')} onChange={(e) => { setForm((s) => ({ ...s, order: e.target.value })) }} />
        </div>
        <div className="flex flex-wrap gap-x-4">
          {isStatus ? <Checkbox label={t('handbooks.isInitial')} checked={form.is_initial} disabled={isSystem || handbook.values.some((x) => x.is_initial && x.is_system && x.id !== value?.id)} onChange={(e) => { setForm((s) => ({ ...s, is_initial: e.target.checked })) }} /> : null}
          <Checkbox label={t('handbooks.isFinal')} checked={form.is_final} disabled={isSystem} onChange={(e) => { setForm((s) => ({ ...s, is_final: e.target.checked })) }} />
          <Checkbox label={t('handbooks.isActive')} checked={form.is_active} disabled={isSystem} onChange={(e) => { setForm((s) => ({ ...s, is_active: e.target.checked })) }} />
        </div>
        {f.is_final ? <p role="alert" className="text-xs text-red-600">{f.is_final}</p> : null}
        {f.is_initial ? <p role="alert" className="text-xs text-red-600">{f.is_initial}</p> : null}
        {f.is_active ? <p role="alert" className="text-xs text-red-600">{f.is_active}</p> : null}
        {f.handbook ? <p role="alert" className="text-xs text-red-600">{f.handbook}</p> : null}
      </form>
    </Drawer>
  )
}

function ValuesPanel({ code }: { code: string }) {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const invalidate = useInvalidateHandbooks()
  const query = useQuery({ queryKey: ['handbooks', code], queryFn: ({ signal }) => api.get<HandbookDetail>('/handbooks/', { code }, { signal }) })
  const [editor, setEditor] = useState<{ value: HandbookValue | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<HandbookValue | null>(null)
  const makeInitial = useMutation({
    mutationFn: (id: number) => api.post<HandbookValue>(`/handbook-values/${String(id)}/make-initial/`),
    onSuccess: invalidate,
    onError: (error) => { pushToast('error', errorMessage(error, t)) },
  })
  const toggleActive = useMutation({
    mutationFn: (v: HandbookValue) => api.patch<HandbookValue>(`/handbook-values/${String(v.id)}/`, { is_active: !v.is_active }),
    onSuccess: invalidate,
    onError: (error) => { pushToast('error', errorMessage(error, t)) },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/handbook-values/${String(id)}/`),
    onSuccess: async () => { await invalidate(); setToDelete(null) },
  })
  const book = query.data
  const isStatus = STATUS_HANDBOOKS.includes(code)

  const columns: Column<HandbookValue>[] = [
    { key: 'order', header: t('handbooks.order'), align: 'right', cell: (v) => v.order },
    {
      key: 'name',
      header: t('handbooks.name'),
      cell: (v) => (
        <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setEditor({ value: v, nonce: Date.now() }) }}>
          {v.name}
        </button>
      ),
    },
    { key: 'code', header: t('handbooks.code'), cell: (v) => v.code || '—' },
    {
      key: 'flags',
      header: t('handbooks.flags'),
      cell: (v) => (
        <span className="flex flex-wrap gap-1">
          {v.is_system ? <Badge tone="neutral" title={t('handbooks.systemHint')}>{t('handbooks.system')}</Badge> : null}
          {v.is_initial ? <Badge tone="info">{t('handbooks.initial')}</Badge> : null}
          {v.is_final ? <Badge tone="success">{t('handbooks.final')}</Badge> : null}
          <Badge tone={v.is_active ? 'neutral' : 'warning'}>{t(v.is_active ? 'common.active' : 'common.inactive')}</Badge>
        </span>
      ),
    },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (v) => (
        <span className="flex justify-end gap-1">
          {isStatus && !v.is_initial && v.is_active && !(book?.values.some((x) => x.is_initial && x.is_system) ?? false) ? (
            <WriteButton permission="handbooks.update" variant="ghost" aria-label={t('handbooks.makeInitialNamed', { name: v.name })} disabled={makeInitial.isPending} onClick={() => { makeInitial.mutate(v.id) }}>
              {t('handbooks.makeInitial')}
            </WriteButton>
          ) : null}
          <WriteButton permission="handbooks.update" variant="ghost" aria-label={t(v.is_active ? 'handbooks.deactivateNamed' : 'handbooks.activateNamed', { name: v.name })} disabled={toggleActive.isPending || (v.is_system && v.is_active)} title={v.is_system && v.is_active ? t('handbooks.systemHint') : undefined} onClick={() => { toggleActive.mutate(v) }}>
            {t(v.is_active ? 'handbooks.deactivate' : 'handbooks.activate')}
          </WriteButton>
          {hasPermission('handbooks.delete') && !v.is_system ? (
            <WriteButton permission="handbooks.delete" variant="ghost" aria-label={t('handbooks.deleteNamed', { name: v.name })} onClick={() => { setToDelete(v) }}>
              {t('common.delete')}
            </WriteButton>
          ) : null}
        </span>
      ),
    },
  ]

  if (query.isError) return <Banner kind="error">{errorMessage(query.error, t)}</Banner>
  if (!book) return <Spinner label={t('table.loading')} />
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{book.name}</h2>
        <WriteButton permission="handbooks.create" variant="primary" onClick={() => { setEditor({ value: null, nonce: Date.now() }) }}>{t('handbooks.addValue')}</WriteButton>
      </div>
      {isStatus ? <p className="text-xs text-muted">{t('handbooks.statusNote')}</p> : null}
      <DataTable caption={book.name} columns={columns} rows={book.values} rowKey={(v) => v.id} empty={<EmptyState title={t('handbooks.emptyValues')} />} />
      {editor ? <ValueDrawer key={editor.nonce} handbook={book} value={editor.value} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('handbooks.deleteTitle')}
        message={t('handbooks.deleteMessage', { name: toDelete?.name ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id) }}
        onCancel={() => { setToDelete(null); remove.reset() }}
      />
    </div>
  )
}

const SCHEMA = { code: codecs.string('') }

/** Справочники: слева список по группам, справа значения выбранного. */
export function HandbooksPage() {
  const { t } = useTranslation()
  const [state, setState] = useUrlState(SCHEMA)
  const list = useQuery({ queryKey: ['handbook-list'], queryFn: ({ signal }) => api.get<HandbookSummary[]>('/handbooks/', undefined, { signal }) })
  const groups = new Map<string, HandbookSummary[]>()
  for (const b of list.data ?? []) groups.set(b.group, [...(groups.get(b.group) ?? []), b])
  const selected = state.code && (list.data ?? []).some((b) => b.code === state.code) ? state.code : (list.data?.[0]?.code ?? '')

  return (
    <div className="space-y-3">
      <PageHeader icon={BookOpen} title={t('nav.handbooks')} />
      {list.isError ? (
        <>
          <Banner kind="error">{errorMessage(list.error, t)}</Banner>
          <Button onClick={() => void list.refetch()}>{t('table.retry')}</Button>
        </>
      ) : !list.data ? (
        <Spinner label={t('table.loading')} />
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[16rem_1fr]">
          <nav aria-label={t('handbooks.list')} className="space-y-2 rounded-card border border-line bg-surface p-3 shadow-card">
            {[...groups.entries()].map(([group, books]) => (
              <div key={group}>
                <p className="px-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{group}</p>
                <ul>
                  {books.map((b) => (
                    <li key={b.code}>
                      <button
                        type="button"
                        aria-current={b.code === selected ? 'true' : undefined}
                        onClick={() => { setState({ code: b.code }) }}
                        className={`flex min-h-9 w-full items-center justify-between gap-2 rounded-control px-2.5 text-left text-sm ${b.code === selected ? 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-900/50 dark:text-brand-100' : 'text-muted hover:bg-surface-2 hover:text-ink'}`}
                      >
                        <span>{b.name}</span>
                        <span className="text-xs text-muted">{b.values_count}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
          <div className="min-w-0">{selected ? <ValuesPanel key={selected} code={selected} /> : <EmptyState title={t('handbooks.empty')} />}</div>
        </div>
      )}
    </div>
  )
}
