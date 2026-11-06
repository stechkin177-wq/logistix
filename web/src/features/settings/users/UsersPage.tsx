import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { Badge } from '../../../shared/ui/Badge'
import { DataTable, type Column } from '../../../shared/ui/DataTable'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { userLabel, useUsersQuery, type CompanyUser } from '../../../shared/users/useUsers'
import { useDepartments } from '../departments/useDepartments'
import { MemberDrawer } from './MemberDrawer'

/** Сотрудники компании: создание/присоединение, роль, отдел, активность (удаления нет). */
export function UsersPage() {
  const { t } = useTranslation()
  const { hasPermission } = useSession()
  const list = useUsersQuery()
  const { departments } = useDepartments()
  const [editor, setEditor] = useState<{ member: CompanyUser | null; nonce: number } | null>(null)

  const columns: Column<CompanyUser>[] = [
    {
      key: 'name',
      header: t('users.fullName'),
      cell: (u) =>
        hasPermission('users.update') ? (
          <button type="button" className="text-left font-medium text-brand-700 hover:underline dark:text-brand-300" onClick={() => { setEditor({ member: u, nonce: Date.now() }) }}>
            {userLabel(u)}
          </button>
        ) : (
          <span className="font-medium">{userLabel(u)}</span>
        ),
    },
    { key: 'login', header: t('users.login'), cell: (u) => u.email ?? u.phone ?? '—' },
    { key: 'role', header: t('users.role'), cell: (u) => u.role_name ?? '—' },
    { key: 'department', header: t('users.department'), cell: (u) => departments.find((d) => d.id === u.department)?.name ?? '—' },
    { key: 'active', header: t('common.status'), cell: (u) => <Badge tone={u.is_active ? 'success' : 'neutral'}>{t(u.is_active ? 'common.active' : 'common.inactive')}</Badge> },
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-base font-semibold">{t('nav.users')}</h1>
        <WriteButton permission="users.create" variant="primary" onClick={() => { setEditor({ member: null, nonce: Date.now() }) }}>{t('users.new')}</WriteButton>
      </div>
      <DataTable
        caption={t('nav.users')}
        columns={columns}
        rows={list.data}
        rowKey={(u) => u.id}
        loading={list.isFetching}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={t('users.empty')} />}
      />
      {editor ? <MemberDrawer key={editor.nonce} member={editor.member} onClose={() => { setEditor(null) }} /> : null}
    </div>
  )
}
