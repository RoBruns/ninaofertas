import { describe, expect, it } from 'vitest'
import { normalizeMoneyInput } from './moneyInput'

describe('normalizeMoneyInput', () => {
  it.each([['1.234,56', '1234.56'], ['1234,56', '1234.56'], ['0,10', '0.10']])('converte %s sem float', (input, expected) => {
    expect(normalizeMoneyInput(input)).toEqual({ value: expected })
  })

  it('recusa valor negativo com mensagem clara', () => {
    expect(normalizeMoneyInput('-5')).toEqual({ error: 'O valor não pode ser negativo.' })
  })
})
