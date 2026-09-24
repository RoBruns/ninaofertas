// Espelha worker/formatter.py (modelo curto): mesma substituição e a linha cuja
// variável ficou vazia sai da mensagem. O modelo com {preco_anterior} usa o
// caminho legado do worker; aqui ele só é substituído, para a prévia.
export const SHORT_MESSAGE_TEMPLATE = '◼️ *{nome}*\n\n💰 {de_por}\n🎟️ Use o cupom: *{cupom}*\n\n🛒 {url}'

export const PREVIEW_EXAMPLE: Readonly<Record<string, string>> = {
  nome: 'Jogo de cama casal 4 peças',
  preco: '129,90',
  preco_anterior: '189,90',
  de_por: 'De ~R$ 189,90~ por *R$ 129,90*',
  desconto: '32',
  cupom: 'NINA10',
  loja: 'Mercado Livre',
  url: 'https://meli.la/exemplo',
  hora: '14:30',
}

const FIELD = /\{(\w+)\}/g

export function renderMessagePreview(template: string, values: Readonly<Record<string, string>> = PREVIEW_EXAMPLE): string {
  const selected = template.trim() || SHORT_MESSAGE_TEMPLATE
  const lines = selected.split('\n').flatMap((line) => {
    const fields = [...line.matchAll(FIELD)].map((match) => match[1])
    if (fields.some((field) => field in values && !values[field])) return []
    return [line.replace(FIELD, (match, field: string) => (field in values ? values[field] : match))]
  })
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}
