import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { errorMessage } from '../../shared/api/errors'
import { Badge } from '../../shared/ui/Badge'
import { Banner } from '../../shared/ui/Banner'
import { DataTable, type Column } from '../../shared/ui/DataTable'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { EmptyState } from '../../shared/ui/EmptyState'
import { Mail, RotateCcw, Plus } from '../../shared/ui/icons'
import { PageHeader } from '../../shared/ui/PageHeader'
import { Pagination } from '../../shared/ui/Pagination'
import { FilterBar, FilterItem } from '../../shared/ui/FilterBar'
import { Select } from '../../shared/ui/Select'
import { TextField } from '../../shared/ui/TextField'
import { WriteButton } from '../../shared/ui/WriteButton'
import { ComposeMailDialog } from './ComposeMailDialog'
import { useMailMessages, useMailStatus, useResendMail } from './hooks'
import type { MailMessage, MailState } from './types'

const STATE_TONE: Record<MailState, 'neutral' | 'success' | 'warning'> = { draft: 'neutral', sent: 'success', failed: 'warning' }
const FILTER_STATES = ['draft', 'sent', 'received'] as const

/** Письма компании: список, фильтры, повторная отправка; новое письмо. */
export function MailPage() {
  const { t, i18n } = useTranslation()
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')
  const [state, setState] = useState('')
  const [composing, setComposing] = useState<number | null>(null)
  const [opened, setOpened] = useState<MailMessage | null>(null)
  const list = useMailMessages({ page, q, state })
  const resend = useResendMail()
  const { configured } = useMailStatus()
  const fmt = (iso: string) => new Date(iso).toLocaleString(i18n.language === 'kk' ? 'kk-KZ' : 'ru-RU')
  const columns: Column<MailMessage>[] = [
    { key: 'subject', header: t('mail.subject'), cell: (m) => (
      <span>
        <span className="font-medium">{m.subject}</span>
      </span>
    ) },
    { key: 'to', header: t('mail.to'), cell: (m) => m.to.join(', ') },
    { key: 'link', header: t('mail.linked'), cell: (m) => (
      <span className="flex flex-col gap-0.5 text-sm">
        {m.order ? <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/orders/${String(m.order)}`}>{m.order_number}</Link> : null}
        {m.trip ? <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/trips/${String(m.trip)}`}>{m.trip_number}</Link> : null}
        {m.client ? <Link className="text-brand-700 hover:underline dark:text-brand-300" to={`/clients/${String(m.client)}`}>{m.client_name}</Link> : null}
        {!m.order && !m.trip && !m.client ? <span className="text-muted">—</span> : null}
      </span>
    ) },
    { key: 'state', header: t('mail.state'), cell: (m) => <Badge tone={STATE_TONE[m.state]}>{t(`mail.states.${m.state}`)}</Badge> },
    { key: 'when', header: t('mail.date'), cell: (m) => fmt(m.sent_at ?? m.created_at) },
    { key: 'by', header: t('mail.author'), cell: (m) => m.created_by_name },
    { key: 'actions', header: '', align: 'right', cell: (m) => m.state === 'sent' ? null : (
      <WriteButton permission="mail.send" variant="ghost" icon={RotateCcw} disabled={resend.isPending} aria-label={t('mail.resendNamed', { subject: m.subject })} onClick={() => { resend.mutate(m.id) }} />
    ) },
  ]
  return (
    <div className="space-y-4">
      <PageHeader
        icon={Mail}
        title={t('nav.mail')}
        subtitle={t('mail.intro')}
        actions={<WriteButton permission="mail.send" variant="primary" icon={Plus} disabled={!configured} title={configured ? undefined : t('mail.notConfigured')} onClick={() => { setComposing(Date.now()) }}>{t('mail.write')}</WriteButton>}
      />
      {!configured ? <Banner kind="warning">{t('mail.notConfigured')}</Banner> : null}
      {resend.isError ? <Banner kind="error">{errorMessage(resend.error, t)}</Banner> : null}
      <FilterBar>
        <FilterItem className="w-auto">
          <TextField label={t('mail.search')} type="search" placeholder={t('mail.searchPlaceholder')} value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
        </FilterItem>
        <FilterItem className="w-48">
          <Select label={t('mail.state')} value={state} placeholder={t('mail.allStates')} options={FILTER_STATES.map((s) => ({ value: s, label: t(`mail.states.${s}`) }))} onChange={(v) => { setState(v); setPage(1) }} />
        </FilterItem>
      </FilterBar>
      <DataTable
        caption={t('nav.mail')}
        onRowClick={setOpened}
        columns={columns}
        rows={list.data?.results}
        rowKey={(m) => m.id}
        loading={list.isPending}
        error={list.isError ? errorMessage(list.error, t) : undefined}
        onRetry={() => { void list.refetch() }}
        empty={<EmptyState icon={Mail} title={t('mail.empty')} hint={t('mail.emptyHint')} />}
      />
      {list.data ? <Pagination page={page} pageSize={50} count={list.data.count} onPage={setPage} /> : null}
      {opened ? (
        <Dialog open title={opened.subject} onClose={() => { setOpened(null) }} footer={<Button onClick={() => { setOpened(null) }}>{t('common.close')}</Button>}>
          <div className="space-y-3 text-sm">
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              <dt className="text-muted">{t('mail.to')}</dt><dd className="break-all">{opened.to.join(', ')}</dd>
              {opened.cc.length > 0 ? <><dt className="text-muted">{t('mail.cc')}</dt><dd className="break-all">{opened.cc.join(', ')}</dd></> : null}
              <dt className="text-muted">{t('mail.date')}</dt><dd>{fmt(opened.sent_at ?? opened.created_at)}</dd>
              <dt className="text-muted">{t('mail.author')}</dt><dd>{opened.created_by_name}</dd>
              <dt className="text-muted">{t('mail.state')}</dt><dd><Badge tone={STATE_TONE[opened.state]}>{t(`mail.states.${opened.state}`)}</Badge></dd>
            </dl>
            {opened.state === 'failed' && opened.error ? <Banner kind="warning">{opened.error}</Banner> : null}
            <div className="whitespace-pre-wrap rounded-control border border-line bg-surface-2 p-3">{opened.body || '—'}</div>
            {opened.attachments.length > 0 ? <p className="text-muted">{t('mail.attachments')}: {opened.attachments.map((a) => a.filename).join(', ')}</p> : null}
          </div>
        </Dialog>
      ) : null}
      {composing !== null ? <ComposeMailDialog key={composing} onClose={() => { setComposing(null) }} /> : null}
    </div>
  )
}
