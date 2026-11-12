/** Texto editável ↔ lista `content.cupons_meli` do bot. */

export type CupomMeliLinha = {
  url: string
  titulo?: string
  codigo?: string
  beneficio?: string
}

/** Uma linha por cupom: `URL | título | código` (código opcional). */
export function serializeCuponsMeli(items: readonly CupomMeliLinha[] | undefined): string {
  return (items ?? [])
    .map((item) => {
      const url = String(item.url ?? '').trim()
      const titulo = String(item.titulo ?? item.beneficio ?? '').trim()
      const codigo = String(item.codigo ?? '').trim()
      if (!url) return ''
      if (codigo) return `${url} | ${titulo || 'Cupom Mercado Livre'} | ${codigo}`
      if (titulo) return `${url} | ${titulo}`
      return url
    })
    .filter(Boolean)
    .join('\n')
}

export function parseCuponsMeli(text: string): CupomMeliLinha[] {
  const out: CupomMeliLinha[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const parts = line.split('|').map((part) => part.trim())
    const url = parts[0] ?? ''
    if (!url) continue
    const titulo = parts[1] ?? ''
    const codigo = parts[2] ?? ''
    out.push({
      url,
      ...(titulo ? { titulo } : {}),
      ...(codigo ? { codigo } : {}),
    })
  }
  return out
}
