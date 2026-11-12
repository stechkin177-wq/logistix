import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../../shared/api/client'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { Badge } from '../../../shared/ui/Badge'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { useUsers } from '../../../shared/users/useUsers'
import { RoleDrawer, type Role } from './RoleDrawer'
import { PageHeader } from '../../../shared/ui/PageHeader'
import { ShieldCheck } from '../../../shared/ui/icons'

export function useRoles(enabled = true) {
  return useQuery({ queryKey: ['roles', 'list'], queryFn: ({ signal }) => api.get<Role[]>('/roles/', undefined, { signal }), enabled })
}

/** Роли и права: системные только для чтения, свои роли - с матрицей прав. */
export function RolesPage() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const roles = useRoles()
  const { users, allowed: usersAllowed } = useUsers()
  const qc = useQueryClient()
  const [editor, setEditor] = useState<{ role: Role | null; nonce: number } | null>(null)
  const [toDelete, setToDelete] = useState<Role | null>(null)
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/roles/${String(id)}/`),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['roles'] }); setToDelete(null) },
  })

  const columns: Column<Role>[] = [
    {
      key: 'name',
      header: t('roles.name'),
      cell: (r) => (
        <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setEditor({ role: r, nonce: Date.now() }) }}>
          {r.name}
        </button>
      ),
    },
    { key: 'system', header: t('roles.kind'), cell: (r) => (r.is_system ? <Badge tone="info">{t('roles.system')}</Badge> : <Badge>{t('roles.custom')}</Badge>) },
    { key: 'perms', header: t('roles.permissionsCount'), align: 'right', cell: (r) => r.permissions.length },
    {
      key: 'members',
      header: t('roles.members'),
      align: 'right',
      cell: (r) => (usersAllowed ? users.filter((u) => u.role === r.id).length : '—'),
    },
    {
      key: 'actions',
      header: <span className="sr-only">{t('common.actions')}</span>,
      align: 'right',
      cell: (r) =>
        !r.is_system && hasPermission('roles.delete') ? (
          <WriteButton permission="roles.delete" variant="ghost" aria-label={t('roles.deleteNamed', { name: r.name })} onClick={() => { setToDelete(r) }}>
            {t('common.delete')}
          </WriteButton>
        ) : null,
    },
  ]

  return (
    <div className="space-y-3">
      <PageHeader icon={ShieldCheck} title={t('nav.roles')}
        actions={
          <>
            <WriteButton permission="roles.create" variant="primary" onClick={() => { setEditor({ role: null, nonce: Date.now() }) }}>{t('roles.new')}</WriteButton>
          </>
        }
      />
      <DataTable
        caption={t('nav.roles')}
        columns={columns}
        rows={roles.data}
        rowKey={(r) => r.id}
        loading={roles.isFetching}
        error={roles.isError ? errorMessage(roles.error, t) : undefined}
        onRetry={() => void roles.refetch()}
        empty={<EmptyState title={t('roles.empty')} />}
      />
      {editor ? <RoleDrawer key={editor.nonce} role={editor.role} onClose={() => { setEditor(null) }} /> : null}
      <ConfirmDialog
        open={toDelete !== null}
        danger
        title={t('roles.deleteTitle')}
        message={t('roles.deleteMessage', { name: toDelete?.name ?? '' })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={() => { if (toDelete) remove.mutate(toDelete.id) }}
        onCancel={() => { setToDelete(null); remove.reset() }}
      />
    </div>
  )
}
