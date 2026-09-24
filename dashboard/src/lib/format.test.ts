import { describe, expect, it } from 'vitest'
import { formatBRL, formatPercent, formatRatio, healthText } from './format'

describe('healthText', () => {
  it.each([
    ['ok', null, 'Sem problemas'],
    ['warning', null, 'Requer atenção'],
    ['error', null, 'Com erro'],
    ['unknown', null, 'Saúde desconhecida'],
    [undefined, null, 'Saúde desconhecida'],
    ['ok', 'Tudo certo', 'Tudo certo'],
  ])('formata status %s com mensagem %s', (status, message, expected) => {
    expect(healthText(status, message)).toBe(expected)
  })
})

describe('formatBRL', () => {
  it.each([
    ['1234.56', 'R$ 1.234,56'],
    ['0.10', 'R$ 0,10'],
    ['-60.00', '-R$ 60,00'],
    ['1000000.00', 'R$ 1.000.000,00'],
    [null, 'sem dados'],
    [undefined, 'sem dados'],
  ])('formata %s sem perder precisão', (input, expected) => {
    expect(formatBRL(input)).toBe(expected)
  })

  it('não converte dinheiro para ponto flutuante', () => {
    const implementation = formatBRL.toString()
    expect(implementation).not.toMatch(/Number\s*\(/)
    expect(implementation).not.toMatch(/parseFloat\s*\(/)
  })
})

it('formata percentuais, razões e ausência de dados', () => {
  expect(formatPercent(0.4035)).toBe('40,4%')
  expect(formatRatio(15)).toBe('15,0x')
  expect(formatPercent(null)).toBe('sem dados')
  expect(formatRatio(undefined)).toBe('sem dados')
})
