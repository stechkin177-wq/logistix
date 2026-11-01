import { describe, expect, it, vi } from 'vitest'
import { setLanguage } from './index'
import kk from './kk.json'
import ru from './ru.json'

type Tree = { [key: string]: string | Tree }

function flatten(tree: Tree, prefix = ''): Record<string, string> {
  return Object.entries(tree).reduce<Record<string, string>>((acc, [key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof value === 'string' ? { ...acc, [path]: value } : { ...acc, ...flatten(value, path) }
  }, {})
}

describe('i18n', () => {
  const ruFlat = flatten(ru)
  const kkFlat = flatten(kk)

  it('ru и kk содержат ровно одинаковый набор ключей', () => {
    expect(Object.keys(kkFlat).sort()).toEqual(Object.keys(ruFlat).sort())
  })

  it('нет пустых значений', () => {
    for (const [key, value] of [...Object.entries(ruFlat), ...Object.entries(kkFlat)]) {
      expect(value.trim(), key).not.toBe('')
    }
  })

  it('плейсхолдеры совпадают в обоих языках', () => {
    const vars = (s: string) => (s.match(/\{\{\w+\}\}/g) ?? []).sort()
    for (const key of Object.keys(ruFlat)) expect(vars(kkFlat[key] ?? ''), key).toEqual(vars(ruFlat[key] ?? ''))
  })

  it('при смене языка обновляется <html lang>', async () => {
    setLanguage('kk')
    await vi.waitFor(() => {
      expect(document.documentElement.lang).toBe('kk')
    })
    setLanguage('ru')
    await vi.waitFor(() => {
      expect(document.documentElement.lang).toBe('ru')
    })
  })
})
