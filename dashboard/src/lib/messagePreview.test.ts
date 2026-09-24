import { describe, expect, it } from 'vitest'
import { PREVIEW_EXAMPLE, renderMessagePreview } from './messagePreview'

describe('renderMessagePreview', () => {
  it('usa o modelo padrão quando o template está vazio', () => {
    expect(renderMessagePreview('')).toBe(
      '◼️ *Jogo de cama casal 4 peças*\n\n'
      + '💰 De ~R$ 189,90~ por *R$ 129,90*\n'
      + '🎟️ Use o cupom: *NINA10*\n\n'
      + '🛒 https://meli.la/exemplo',
    )
  })

  it('tira a linha cuja variável ficou vazia, como o worker', () => {
    const semCupom = renderMessagePreview('', { ...PREVIEW_EXAMPLE, cupom: '' })
    expect(semCupom).not.toContain('cupom')
    expect(semCupom).not.toMatch(/\n{3,}/)
  })

  it('substitui as variáveis de um template do bot', () => {
    expect(renderMessagePreview('🔥 {nome}\n✅ R$ {preco}\n⏰ {hora}')).toBe('🔥 Jogo de cama casal 4 peças\n✅ R$ 129,90\n⏰ 14:30')
  })
})
