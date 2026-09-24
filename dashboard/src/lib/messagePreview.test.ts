import { describe, expect, it } from 'vitest'
import { renderMessagePreview, SHORT_MESSAGE_TEMPLATE } from './messagePreview'

describe('renderMessagePreview', () => {
  it('renderiza o modelo curto quando o template esta vazio', () => {
    expect(renderMessagePreview('')).toBe(
      SHORT_MESSAGE_TEMPLATE
        .replace('{nome}', 'Jogo de cama casal 4 peças')
        .replace('{preco}', '129,90')
        .replace('{url}', 'https://meli.la/exemplo')
        .replace('{hora}', '14:30'),
    )
  })
})
