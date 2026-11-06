import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../../shared/api/client'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { Button } from '../../../shared/ui/Button'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { Dialog } from '../../../shared/ui/Dialog'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { TextField } from '../../../shared/ui/TextField'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { useDepartments, type Department } from './useDepartments'

function DepartmentDialog({ department, onClose }: { department: Department | null; onClose: () => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [name, setName] = useState(department?.name ?? '')
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const ref = useRef<HTMLFormElement>(null)
  useFocusInvalid(ref, errors)
  const permission = department ? 'users.update' : 'users.create'
  const save = useMutation({
    mutationFn: (body: { name: string }) =>
      department ? api.patch<Department>(`/departments/${String(department.id)}/`, body) : api.post<Department>('/departments/', body),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['departments'] }); onClose() },
    onError: (error) => { setErrors(serverErrors(error, t, (p) => p === 'name')) },
  })
  const submit = () => {
    if (!name.trim()) {
      setErrors({ fields: { name: t('errors.requiredField') }, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    save.mutate({ name: name.trim() })
  }
  return (
    <Dialog
      open
      title={department ? t('departments.edit') : t('departments.new')}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission={permission} variant="primary" onClick={submit} disabled={save.isPending}>{t('common.save')}</WriteButton>
        </>
      }
    >
      <form ref={ref} noValidate className="space-y-2" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <FormBanner message={errors.banner} />
        <TextField label={t('departments.name')} required data-autofocus value={name} error={errors.fields.name} onChange={(e) => { setName(e.target.value) }} />
      </form>
    </Dialog>
  )
}

/** Отделы: список, создание/переименование, удаление (права раздела users). */
export function DepartmentsPage() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const list = useDepartments()
  const qc = useQueryClient()
  const [editor, setEditor] = useState<{ department: Department | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<Department | null>(null)
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/departments/${String(id)}/`),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['departments'] }); await qc.invalidateQueries({ queryKey: ['users'] }); setToDelete(null) },
  })

  const columns: Column<Department>[] = [
    {
      key: 'name',
      header: t('departments.name'),
      cell: (d) => (
        <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setEditor({ department: d, nonce: Date.now() }) }}>
          {d.name}
        </button>
      ),
    },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (d) =>
        hasPermission('users.delete') ? (
          <WriteButton permission="users.delete" variant="ghost" aria-label={t('departments.deleteNamed', { name: d.name })} onClick={() => { setToDelete(d) }}>
            {t('common.delete')}
          </WriteButton>
        ) : null,
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-base font-semibold">{t('nav.departments')}</h1>
        <WriteButton permission="users.create" variant="primary" onClick={() => { setEditor({ department: null, nonce: Date.now() }) }}>{t('departments.new')}</WriteButton>
      </div>
      <DataTable
        caption={t('nav.departments')}
        columns={columns}
        rows={list.data}
        rowKey={(d) => d.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={t('departments.empty')} hint={t('departments.emptyHint')} />}
      />
      {editor ? <DepartmentDialog key={editor.nonce} department={editor.department} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('departments.deleteTitle')}
        message={t('departments.deleteMessage', { name: toDelete?.name ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id) }}
        onCancel={() => { setToDelete(null); remove.reset() }}
      />
    </div>
  )
}
