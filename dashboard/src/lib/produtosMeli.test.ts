import { describe, expect, it } from 'vitest'
import {
  extrairLinhasDeMaisVendidosHtml,
  parseProdutosMeli,
  serializeProdutosMeli,
} from './produtosMeli'

describe('produtosMeli', () => {
  it('parseia linha completa e ignora URL sem MLB', () => {
    const text = [
      'https://www.mercadolivre.com.br/x/p/MLB123 | Panela | 89.90 | 129.90 | https://img/a.webp',
      'https://www.mercadolivre.com.br/ofertas | sem id | 10',
      'https://shopee.com.br/x | outra loja | 10',
    ].join('\n')
    const parsed = parseProdutosMeli(text, { agoraIso: '2026-11-23T12:00:00.000Z' })
    expect(parsed).toEqual([
      {
        url: 'https://www.mercadolivre.com.br/x/p/MLB123',
        titulo: 'Panela',
        preco: '89.90',
        preco_anterior: '129.90',
        imagem: 'https://img/a.webp',
        adicionado_em: '2026-11-23T12:00:00.000Z',
      },
    ])
  })

  it('preserva adicionado_em de item existente na mesma URL', () => {
    const parsed = parseProdutosMeli(
      'https://www.mercadolivre.com.br/p/MLB9 | X | 10',
      {
        agoraIso: '2026-11-23T18:00:00.000Z',
        existentes: [
          {
            url: 'https://www.mercadolivre.com.br/p/MLB9',
            adicionado_em: '2026-11-22T10:00:00.000Z',
          },
        ],
      },
    )
    expect(parsed[0]?.adicionado_em).toBe('2026-11-22T10:00:00.000Z')
  })

  it('serializa com pipes', () => {
    expect(
      serializeProdutosMeli([
        {
          url: 'https://www.mercadolivre.com.br/p/MLB1',
          titulo: 'Item',
          preco: '10',
        },
      ]),
    ).toBe('https://www.mercadolivre.com.br/p/MLB1 | Item | 10')
  })

  it('extrai polycards do HTML de mais vendidos', () => {
    const card = {
      metadata: { id: 'MLB555', url: 'produto.mercadolivre.com.br/MLB-555-x' },
      components: [
        { type: 'title', title: { text: 'Cadeira' } },
        {
          type: 'price',
          price: {
            current_price: { value: 199.9 },
            price_labels: [{ values: [{ price: { previous: true, value: 299 } }] }],
          },
        },
      ],
      pictures: { pictures: [{ id: 'ABC' }] },
    }
    const html =
      '"best_sellers_configuration":{"category":"MLB1574"},"polycards":' +
      JSON.stringify([card])
    const linhas = extrairLinhasDeMaisVendidosHtml(html)
    expect(linhas).toHaveLength(1)
    expect(linhas[0]).toContain('Cadeira')
    expect(linhas[0]).toContain('199.9')
    expect(linhas[0]).toContain('https://http2.mlstatic.com/D_NQ_NP_ABC-O.webp')
  })
})
