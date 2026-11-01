import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { DataTable, type Column } from './DataTable'

interface Row { id: number; name: string }
const COLUMNS: Column<Row>[] = [
  { key: 'name', header: 'Название', sortKey: 'name', cell: (r) => r.name },
  { key: 'plain', header: 'Без сортировки', cell: () => 'x' },
]

function setup(props: Partial<Parameters<typeof DataTable<Row>>[0]> = {}) {
  return render(
    <I18nextProvider i18n={i18n}>
      <DataTable caption="Тест" columns={COLUMNS} rows={[{ id: 1, name: 'Альфа' }]} rowKey={(r) => r.id} {...props} />
    </I18nextProvider>,
  )
}

describe('DataTable', () => {
  it('строки', () => {
    setup()
    expect(screen.getByText('Альфа')).toBeInTheDocument()
  })
  it('загрузка', () => {
    setup({ rows: undefined, loading: true })
    expect(screen.getByText('Загрузка данных')).toBeInTheDocument()
  })
  it('пусто: показывает переданное состояние', () => {
    setup({ rows: [], empty: <p>Пусто, добавьте</p> })
    expect(screen.getByText('Пусто, добавьте')).toBeInTheDocument()
    expect(screen.queryByText('Альфа')).not.toBeInTheDocument()
  })
  it('ошибка с повтором', async () => {
    const retry = vi.fn()
    setup({ rows: undefined, error: 'Сломалось', onRetry: retry })
    expect(screen.getByRole('alert')).toHaveTextContent('Сломалось')
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(retry).toHaveBeenCalled()
  })
  it('сортировка: asc, затем desc; несортируемые колонки без кнопки', async () => {
    const onChange = vi.fn()
    const { rerender } = setup({ ordering: 'created_at', onOrderingChange: onChange })
    expect(screen.queryByRole('button', { name: /Без сортировки/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Сортировать по: Название' }))
    expect(onChange).toHaveBeenLastCalledWith('name')
    rerender(
      <I18nextProvider i18n={i18n}>
        <DataTable caption="Тест" columns={COLUMNS} rows={[]} rowKey={(r) => r.id} ordering="name" onOrderingChange={onChange} />
      </I18nextProvider>,
    )
    expect(screen.getByRole('columnheader', { name: /Название/ })).toHaveAttribute('aria-sort', 'ascending')
    await userEvent.click(screen.getByRole('button', { name: 'Сортировать по: Название' }))
    expect(onChange).toHaveBeenLastCalledWith('-name')
  })
})
