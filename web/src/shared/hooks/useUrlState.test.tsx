import { act, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import { codecs, useUrlState } from './useUrlState'

const SCHEMA = {
  q: codecs.string(''),
  page: codecs.positiveInt(1),
  ordering: codecs.oneOf(['name', '-name', 'created_at'] as const, 'name'),
  status: codecs.numberList(),
  unassigned: codecs.flag(),
  from: codecs.date(),
}

function renderUrlState(path: string) {
  const router = createMemoryRouter([{ path: '*', element: <Holder /> }], { initialEntries: [path] })
  const out: { current: ReturnType<typeof useUrlState<typeof SCHEMA>> | null } = { current: null }
  function Holder(): ReactNode {
    out.current = useUrlState(SCHEMA)
    return null
  }
  render(<RouterProvider router={router} />)
  return { router, out }
}

describe('useUrlState', () => {
  it('мусорные значения в адресе дают значения по умолчанию', () => {
    const { out } = renderUrlState('/?page=abc&ordering=DROP%20TABLE&status=1,x,,-3&unassigned=maybe&from=2024-13-45&q=%E0%A4%A')
    const [state] = out.current!
    expect(state.page).toBe(1)
    expect(state.ordering).toBe('name')
    expect(state.status).toEqual([1])
    expect(state.unassigned).toBe(false)
    expect(state.from).toBe('')
  })

  it('отрицательная и нулевая страница сбрасываются в 1', () => {
    expect(renderUrlState('/?page=0').out.current![0].page).toBe(1)
    expect(renderUrlState('/?page=-5').out.current![0].page).toBe(1)
    expect(renderUrlState('/?page=1e9999').out.current![0].page).toBe(1)
  })

  it('читает корректные значения', () => {
    const { out } = renderUrlState('/?q=abc&page=3&ordering=-name&status=1,2&status=5&unassigned=1&from=2024-02-29')
    const [state] = out.current!
    expect(state).toEqual({ q: 'abc', page: 3, ordering: '-name', status: [1, 2, 5], unassigned: true, from: '2024-02-29' })
  })

  it('круговой обход: запись в адрес и чтение обратно; значения по умолчанию из адреса убираются', () => {
    const { out, router } = renderUrlState('/')
    act(() => {
      out.current![1]({ q: 'тест', page: 2, status: [3, 4], unassigned: true, from: '2024-05-01' })
    })
    expect(router.state.location.search).toContain('q=%D1%82%D0%B5%D1%81%D1%82')
    expect(router.state.location.search).toContain('status=3%2C4')
    expect(out.current![0]).toMatchObject({ q: 'тест', page: 2, status: [3, 4], unassigned: true, from: '2024-05-01' })
    act(() => {
      out.current![1]({ page: 1, unassigned: false, status: [] })
    })
    expect(router.state.location.search).not.toContain('page')
    expect(router.state.location.search).not.toContain('unassigned')
    expect(router.state.location.search).not.toContain('status')
  })

  it('неизвестные параметры адреса сохраняются', () => {
    const { out, router } = renderUrlState('/?tab=finance')
    act(() => {
      out.current![1]({ q: 'x' })
    })
    expect(router.state.location.search).toContain('tab=finance')
  })
})
