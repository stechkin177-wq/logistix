import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../../shared/api/client'
import { errorMessage } from '../../../shared/api/errors'
import { useCanWrite } from '../../../shared/auth/useCanWrite'
import { NO_ERRORS, serverErrors, type FormErrors } from '../../../shared/forms/serverErrors'
import { useFocusInvalid } from '../../../shared/forms/useFocusInvalid'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { Drawer } from '../../../shared/ui/Drawer'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { TextField } from '../../../shared/ui/TextField'
import { WriteButton } from '../../../shared/ui/WriteButton'

interface Rule { kind: string; name: string; description: string; template: string; digits: number; next_value: number; sample: string }

const PLACEHOLDERS = ['{year}', '{index}', '{order}', '{n}']

function RuleDrawer({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const canSave = useCanWrite('numbering.update')
  const [form, setForm] = useState({ template: rule.template, digits: String(rule.digits), next_value: String(rule.next_value) })
  const [errors, setErrors] = useState<FormErrors>(NO_ERRORS)
  const ref = useRef<HTMLFormElement>(null)
  useFocusInvalid(ref, errors)
  const save = useMutation({
    mutationFn: (body: { template: string; digits: number; next_value: number }) => api.patch<Rule>(`/numbering/${rule.kind}/`, body),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['numbering'] }); onClose() },
    onError: (error) => { setErrors(serverErrors(error, t, (p) => ['template', 'digits', 'next_value'].includes(p))) },
  })
  const lowering = /^\d{1,10}$/.test(form.next_value) && Number(form.next_value) < rule.next_value

  const submit = () => {
    const local: Record<string, string> = {}
    if (!form.template.trim()) local.template = t('errors.requiredField')
    if (!/^\d{1,2}$/.test(form.digits) || Number(form.digits) > 10) local.digits = t('numbering.digitsRange')
    if (!/^\d{1,10}$/.test(form.next_value) || Number(form.next_value) < 1) local.next_value = t('numbering.nextRange')
    if (Object.keys(local).length > 0) {
      setErrors({ fields: local, banner: undefined })
      return
    }
    setErrors(NO_ERRORS)
    save.mutate({ template: form.template.trim(), digits: Number(form.digits), next_value: Number(form.next_value) })
  }
  const f = errors.fields
  return (
    <Drawer
      open
      title={t('numbering.editNamed', { name: rule.name })}
      onClose={onClose}
      busy={save.isPending}
      footer={
        <>
          <Button onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <WriteButton permission="numbering.update" variant="primary" onClick={submit} disabled={save.isPending}>{save.isPending ? t('common.saving') : t('common.save')}</WriteButton>
        </>
      }
    >
      <form ref={ref} noValidate className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (canSave) submit() }}>
        <FormBanner message={errors.banner} />
        <p className="text-sm text-slate-600 dark:text-slate-300">{rule.description}</p>
        <TextField label={t('numbering.template')} required value={form.template} error={f.template} hint={t('numbering.placeholders', { list: PLACEHOLDERS.join(' ') })} onChange={(e) => { setForm((s) => ({ ...s, template: e.target.value })) }} />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <TextField label={t('numbering.digits')} inputMode="numeric" value={form.digits} error={f.digits} hint={t('numbering.digitsHint')} onChange={(e) => { setForm((s) => ({ ...s, digits: e.target.value })) }} />
          <TextField label={t('numbering.nextValue')} inputMode="numeric" value={form.next_value} error={f.next_value} onChange={(e) => { setForm((s) => ({ ...s, next_value: e.target.value })) }} />
        </div>
        {lowering ? <Banner kind="warning">{t('numbering.lowerWarning')}</Banner> : null}
      </form>
    </Drawer>
  )
}

/** Нумерация: 5 правил, шаблон, разрядность, счётчик и пример от сервера. */
export function NumberingPage() {
  const { t } = useTranslation()
  const list = useQuery({ queryKey: ['numbering'], queryFn: ({ signal }) => api.get<Rule[]>('/numbering/', undefined, { signal }) })
  const [editor, setEditor] = useState<{ rule: Rule; nonce: number } | null>(null)
  const columns: Column<Rule>[] = [
    { key: 'name', header: t('numbering.document'), cell: (r) => <span className="font-medium">{r.name}</span> },
    { key: 'description', header: t('numbering.description'), cell: (r) => r.description },
    { key: 'template', header: t('numbering.template'), cell: (r) => <code className="text-xs">{r.template}</code> },
    { key: 'digits', header: t('numbering.digits'), align: 'right', cell: (r) => r.digits },
    { key: 'next', header: t('numbering.nextValue'), align: 'right', cell: (r) => r.next_value },
    { key: 'sample', header: t('numbering.sample'), cell: (r) => <code className="text-xs">{r.sample}</code> },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (r) => (
        <WriteButton permission="numbering.update" aria-label={t('numbering.editNamed', { name: r.name })} onClick={() => { setEditor({ rule: r, nonce: Date.now() }) }}>{t('common.edit')}</WriteButton>
      ),
    },
  ]
  return (
    <div className="space-y-3">
      <h1 className="text-base font-semibold">{t('nav.numbering')}</h1>
      <DataTable
        caption={t('nav.numbering')}
        columns={columns}
        rows={list.data}
        rowKey={(r) => r.kind}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={t('numbering.empty')} />}
      />
      {editor ? <RuleDrawer key={editor.nonce} rule={editor.rule} onClose={() => { setEditor(null) }} /> : null}
    </div>
  )
}
