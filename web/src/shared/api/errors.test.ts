import { describe, expect, it } from 'vitest'
import { ApiError, errorMessage } from './errors'

const t = (key: string) => `T:${key}`

describe('errorMessage: коды документов', () => {
  it.each(['template_invalid', 'source_not_ready'])('%s показывает detail сервера', (code) => {
    expect(errorMessage(new ApiError(400, code, 'Метка {{ x }}, строка 3'), t)).toBe('Метка {{ x }}, строка 3')
  })

  it.each(['template_invalid', 'source_not_ready'])('%s без detail берёт перевод', (code) => {
    expect(errorMessage(new ApiError(400, code, ''), t)).toBe(`T:errors.documents.${code}`)
  })

  it('прочие коды документов остаются переводом', () => {
    expect(errorMessage(new ApiError(400, 'template_missing', 'raw'), t)).toBe('T:errors.documents.template_missing')
  })
})
