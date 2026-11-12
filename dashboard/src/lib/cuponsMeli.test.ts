import { describe, expect, it } from 'vitest'
import { parseCuponsMeli, serializeCuponsMeli } from './cuponsMeli'

describe('cuponsMeli', () => {
  it('aceita espaços no título e código opcional', () => {
    const text = [
      'https://lista.mercadolivre.com.br/_Container_14548284?coupon_campaign_id=14548284 | 30% OFF em LIQUIDA',
      'https://meli.la/abc | 25% OFF acima de R$79 | HOJENOML',
      '',
      'https://meli.la/sozinho',
    ].join('\n')
    const parsed = parseCuponsMeli(text)
    expect(parsed).toEqual([
      {
        url: 'https://lista.mercadolivre.com.br/_Container_14548284?coupon_campaign_id=14548284',
        titulo: '30% OFF em LIQUIDA',
      },
      {
        url: 'https://meli.la/abc',
        titulo: '25% OFF acima de R$79',
        codigo: 'HOJENOML',
      },
      { url: 'https://meli.la/sozinho' },
    ])
  })

  it('serializa de volta com espaços em volta do |', () => {
    expect(
      serializeCuponsMeli([
        {
          url: 'https://lista.mercadolivre.com.br/_Container_1?coupon_campaign_id=1',
          titulo: '30% OFF em LIQUIDA',
        },
      ]),
    ).toBe(
      'https://lista.mercadolivre.com.br/_Container_1?coupon_campaign_id=1 | 30% OFF em LIQUIDA',
    )
  })
})
