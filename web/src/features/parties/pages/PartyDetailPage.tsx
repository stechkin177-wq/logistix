import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError, errorMessage } from '../../../shared/api/errors'
import { useSession } from '../../../shared/auth/useSession'
import { EntityHistory } from '../../../shared/entity/EntityHistory'
import { codecs, useUrlState } from '../../../shared/hooks/useUrlState'
import { Badge } from '../../../shared/ui/Badge'
import { Banner } from '../../../shared/ui/Banner'
import { Button } from '../../../shared/ui/Button'
import { Card, CardBody, CardHeader } from '../../../shared/ui/Card'
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog'
import { DateTime } from '../../../shared/ui/DateTime'
import { EmptyState } from '../../../shared/ui/EmptyState'
import { Building2, FileText, History, Landmark, Package, Phone, Route, Trash2, Truck, UserRound } from '../../../shared/ui/icons'
import { FormBanner } from '../../../shared/ui/FormBanner'
import { Money } from '../../../shared/ui/Money'
import { PageHeader } from '../../../shared/ui/PageHeader'
import { Spinner } from '../../../shared/ui/Spinner'
import { Tabs, type TabDef } from '../../../shared/ui/Tabs'
import { WriteButton } from '../../../shared/ui/WriteButton'
import { IssueDocumentButton } from '../../documents/IssueDocumentButton'
import { useCurrencies, useOrderList } from '../../orders/hooks'
import { useTripList } from '../../trips/hooks'
import { ContactsEditor } from '../components/ContactsEditor'
import { PartyMainFields, PartyRequisitesFields } from '../components/PartyFields'
import { usePartyForm } from '../components/usePartyForm'
import { useDeleteParty, useParty } from '../hooks'
import type { Client, Party, PartyKind } from '../types'

const TABS = ['main', 'contacts', 'requisites', 'documents', 'work', 'history'] as const
const SCHEMA = { tab: codecs.oneOf(TABS, 'main') }
const FORM_ID = 'party-card-form'

const NO_FILTERS = {
  q: '', status: [] as number[], client: null as number | null, carrier: null as number | null,
  loading_from: '', loading_to: '', created_from: '', created_to: '', completed_from: '', completed_to: '', unassigned: false,
}

/** Последние заказы клиента. */
function ClientWork({ party }: { party: Party }) {
  const { t } = useTranslation()
  const { codeOf } = useCurrencies()
  const list = useOrderList({ ...NO_FILTERS, client: party.id, ordering: '-created_at', page: 1, pageSize: 10 })
  const rows = list.data?.results ?? []
  return (
    <Card>
      <CardHeader
        title={t('parties.recentOrders')}
        actions={<Link to={`/orders?client=${String(party.id)}`} className="text-sm text-brand-700 hover:underline dark:text-brand-300">{t('parties.allOrders')}</Link>}
      />
      {list.isPending ? <div className="p-4"><Spinner label={t('common.loading')} /></div> : null}
      {list.isError ? <div className="p-4"><Banner kind="error">{errorMessage(list.error, t)}</Banner></div> : null}
      {list.data && rows.length === 0 ? <EmptyState icon={Package} title={t('parties.noOrders')} /> : null}
      {rows.length > 0 ? (
        <ul className="divide-y divide-line text-sm">
          {rows.map((o) => (
            <li key={o.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3">
              <span className="min-w-0">
                <Link to={`/orders/${String(o.id)}`} className="font-medium text-brand-700 hover:underline dark:text-brand-300">{o.number}</Link>
                <span className="ml-2 text-muted">{o.route}</span>
              </span>
              <span className="flex items-center gap-3">
                <Badge>{o.status_name}</Badge>
                <Money value={o.client_rate} currency={codeOf(o.currency) || undefined} />
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  )
}

/** Последние рейсы перевозчика. */
function CarrierWork({ party }: { party: Party }) {
  const { t } = useTranslation()
  const { codeOf } = useCurrencies()
  const list = useTripList({ q: '', order: null, status: null, carrier: party.id, consolidated: false, page: 1, pageSize: 10 })
  const rows = list.data?.results ?? []
  return (
    <Card>
      <CardHeader
        title={t('parties.recentTrips')}
        actions={<Link to={`/trips?carrier=${String(party.id)}`} className="text-sm text-brand-700 hover:underline dark:text-brand-300">{t('parties.allTrips')}</Link>}
      />
      {list.isPending ? <div className="p-4"><Spinner label={t('common.loading')} /></div> : null}
      {list.isError ? <div className="p-4"><Banner kind="error">{errorMessage(list.error, t)}</Banner></div> : null}
      {list.data && rows.length === 0 ? <EmptyState icon={Route} title={t('parties.noTrips')} /> : null}
      {rows.length > 0 ? (
        <ul className="divide-y divide-line text-sm">
          {rows.map((trip) => (
            <li key={trip.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3">
              <span className="min-w-0">
                <Link to={`/trips/${String(trip.id)}`} className="font-medium text-brand-700 hover:underline dark:text-brand-300">{trip.number}</Link>
                <span className="ml-2 text-muted">{[trip.vehicle_plate, trip.driver_name].filter(Boolean).join(' / ')}</span>
              </span>
              <span className="flex items-center gap-3">
                <Badge>{trip.status_name}</Badge>
                <Money value={trip.carrier_price} currency={codeOf(trip.currency) || undefined} />
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  )
}

function Content({ kind, party, onSaved }: { kind: PartyKind; party: Party; onSaved: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { hasPermission } = useSession()
  const remove = useDeleteParty(kind)
  const [state, setState] = useUrlState(SCHEMA)
  const [deleting, setDeleting] = useState(false)
  const { api, formRef } = usePartyForm(kind, party, onSaved)
  const permission = `${kind}.update`

  const tabs: TabDef[] = [
    { key: 'main', label: t('parties.tabMain'), icon: kind === 'clients' ? Building2 : Truck },
    { key: 'contacts', label: t('parties.tabContacts'), icon: Phone, count: party.contacts.length },
    { key: 'requisites', label: t('parties.tabRequisites'), icon: Landmark },
    ...(kind === 'clients' ? [{ key: 'documents', label: t('parties.tabDocuments'), icon: FileText }] : []),
    { key: 'work', label: t(kind === 'clients' ? 'parties.tabOrders' : 'parties.tabTrips'), icon: kind === 'clients' ? Package : Route, count: kind === 'clients' ? (party as Client).orders_count : undefined },
    { key: 'history', label: t('parties.tabHistory'), icon: History },
  ]
  const active = tabs.some((x) => x.key === state.tab) ? state.tab : 'main'
  const inForm = active === 'main' || active === 'contacts' || active === 'requisites'
  const subtitle = [party.type_name, party.bin_iin].filter(Boolean).join(' · ')

  return (
    <div className="space-y-4">
      <PageHeader
        back={{ to: `/${kind}`, label: t(`nav.${kind}`) }}
        title={party.name}
        subtitle={subtitle || undefined}
        meta={<Badge tone={party.status === 'active' ? 'success' : 'neutral'}>{t(party.status === 'active' ? 'common.active' : 'common.inactive')}</Badge>}
        actions={
          <>
            {hasPermission(`${kind}.delete`) ? (
              <WriteButton permission={`${kind}.delete`} variant="danger" icon={Trash2} onClick={() => { setDeleting(true) }}>{t('common.delete')}</WriteButton>
            ) : null}
            <WriteButton permission={permission} variant="primary" type="submit" form={FORM_ID} disabled={api.isPending}>
              {api.isPending ? t('common.saving') : t('common.save')}
            </WriteButton>
          </>
        }
      />
      <Tabs tabs={tabs} active={active} label={t('parties.tabs')} onChange={(tab) => { setState({ tab: TABS.find((x) => x === tab) ?? 'main' }, { replace: true }) }} />
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}>
        {/* форма одна на три вкладки: введённое не теряется при переключении, «Сохранить» отправляет всё сразу */}
        <form id={FORM_ID} ref={formRef} noValidate onSubmit={(event) => { event.preventDefault(); if (api.canSave) api.submit() }} hidden={!inForm}>
          <div className="space-y-3">
            <FormBanner message={api.errors.banner} />
            {active === 'main' ? <Card><CardBody><PartyMainFields kind={kind} api={api} /></CardBody></Card> : null}
            {active === 'contacts' ? <Card><CardBody><ContactsEditor disabled={!api.canSave} rows={api.form.contacts} errors={api.errors.fields} onChange={(rows) => { api.set('contacts', rows) }} /></CardBody></Card> : null}
            {active === 'requisites' ? <Card><CardBody><PartyRequisitesFields api={api} /></CardBody></Card> : null}
          </div>
        </form>
        {active === 'documents' ? (
          <Card>
            <CardHeader title={t('documents.title')} hint={t('parties.documentsHint')} />
            <CardBody className="flex flex-wrap gap-2">
              <IssueDocumentButton kind="contract" source={{ client: party.id }} label={t('documents.kind.contract')} />
            </CardBody>
          </Card>
        ) : null}
        {active === 'work' ? (kind === 'clients' ? <ClientWork party={party} /> : <CarrierWork party={party} />) : null}
        {active === 'history' ? <EntityHistory objectType={`forwarding.${kind === 'clients' ? 'client' : 'carrier'}`} objectId={party.id} /> : null}
      </div>
      <p className="flex items-center gap-1.5 text-xs text-muted">
        <UserRound className="size-3.5" aria-hidden="true" />
        {t('parties.created')}: <DateTime value={party.created_at} dateOnly />
      </p>
      <ConfirmDialog
        open={deleting}
        danger
        title={t(`parties.${kind}.deleteTitle`)}
        message={t(`parties.${kind}.deleteMessage`, { name: party.name })}
        confirmLabel={t('common.delete')}
        busy={remove.isPending}
        error={remove.isError ? errorMessage(remove.error, t) : undefined}
        onConfirm={() => { remove.mutate(party.id, { onSuccess: () => void navigate(`/${kind}`, { replace: true }) }) }}
        onCancel={() => { setDeleting(false); remove.reset() }}
      />
    </div>
  )
}

/** Карточка клиента или перевозчика: вкладки Основное / Контакты / Реквизиты / Документы / Заказы (Рейсы) / История. */
export function PartyDetailPage({ kind }: { kind: PartyKind }) {
  const { t } = useTranslation()
  const params = useParams()
  const rawId = params.id ?? ''
  const id = /^\d{1,12}$/.test(rawId) ? Number(rawId) : null
  const query = useParty(kind, id)
  // после сохранения форма пересоздаётся из свежих данных (а не при каждом фоновом обновлении: введённое не пропадёт)
  const [version, setVersion] = useState(0)

  if (id === null || (query.isError && query.error instanceof ApiError && query.error.status === 404)) {
    return (
      <EmptyState icon={kind === 'clients' ? Building2 : Truck} title={t(`parties.${kind}.notFound`)}>
        <Link to={`/${kind}`} className="text-sm text-brand-700 hover:underline dark:text-brand-300">{t(`nav.${kind}`)}</Link>
      </EmptyState>
    )
  }
  if (query.isError) {
    return (
      <div className="space-y-2">
        <Banner kind="error">{errorMessage(query.error, t)}</Banner>
        <Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>
      </div>
    )
  }
  if (!query.data) return <Spinner label={t('common.loading')} />
  return (
    <Content
      key={`${String(query.data.id)}-${String(version)}`}
      kind={kind}
      party={query.data}
      onSaved={() => { void query.refetch().then(() => { setVersion((v) => v + 1) }) }}
    />
  )
}
