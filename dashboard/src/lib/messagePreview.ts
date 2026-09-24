export const SHORT_MESSAGE_TEMPLATE = '🔥 {nome}\n\n✅ R$ {preco}\n\n{url}\n\n⏰ {hora}'

const example = {
  nome: 'Jogo de cama casal 4 peças',
  preco: '129,90',
  preco_anterior: '189,90',
  desconto: '32',
  loja: 'Mercado Livre',
  url: 'https://meli.la/exemplo',
  hora: '14:30',
}

export function renderMessagePreview(template: string): string {
  const selected = template.trim() || SHORT_MESSAGE_TEMPLATE
  return selected.replace(
    /\{(nome|preco|preco_anterior|desconto|loja|url|hora)\}/g,
    (_match, key: keyof typeof example) => example[key],
  )
}
