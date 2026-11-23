/** Texto editável ↔ lista `content.produtos_meli` do bot. */

export type ProdutoMeliLinha = {
  url: string
  titulo: string
  preco: string
  preco_anterior?: string
  imagem?: string
  adicionado_em?: string
}

/** Aceita o shape frouxo do OpenAPI (`{ [key: string]: unknown }[]`). */
export type ProdutoMeliEntrada = {
  url?: unknown
  titulo?: unknown
  preco?: unknown
  preco_anterior?: unknown
  imagem?: unknown
  adicionado_em?: unknown
  [key: string]: unknown
}

const MLB_RE = /MLB-?(\d+)/i

/** Uma linha por produto: `URL | título | preço | preço_anterior | imagem`. */
export function serializeProdutosMeli(items: readonly ProdutoMeliEntrada[] | undefined): string {
  return (items ?? [])
    .map((item) => {
      const url = String(item.url ?? '').trim()
      if (!url) return ''
      const titulo = String(item.titulo ?? '').trim()
      const preco = String(item.preco ?? '').trim()
      const anterior = String(item.preco_anterior ?? '').trim()
      const imagem = String(item.imagem ?? '').trim()
      const parts = [url, titulo || 'Produto Mercado Livre', preco]
      if (anterior || imagem) parts.push(anterior)
      if (imagem) parts.push(imagem)
      return parts.join(' | ')
    })
    .filter(Boolean)
    .join('\n')
}

export function parseProdutosMeli(
  text: string,
  options: {
    agoraIso?: string
    existentes?: readonly ProdutoMeliEntrada[]
  } = {},
): ProdutoMeliLinha[] {
  const agoraIso = options.agoraIso ?? new Date().toISOString()
  const porUrl = new Map<string, string>()
  for (const item of options.existentes ?? []) {
    const url = String(item.url ?? '').trim()
    const adicionado = String(item.adicionado_em ?? '').trim()
    if (url && adicionado) porUrl.set(url, adicionado)
  }
  const out: ProdutoMeliLinha[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const parts = line.split('|').map((part) => part.trim())
    const url = parts[0] ?? ''
    if (!url) continue
    if (!url.toLowerCase().includes('mercadolivre.com.br') || !MLB_RE.test(url)) continue
    const titulo = parts[1] ?? ''
    const preco = parts[2] ?? ''
    if (!preco) continue
    const anterior = parts[3] ?? ''
    const imagem = parts[4] ?? ''
    const mlbMatch = url.match(MLB_RE)
    const mlbId = mlbMatch ? `MLB${mlbMatch[1]}` : 'MLB'
    out.push({
      url,
      titulo: titulo || `Produto ${mlbId}`,
      preco,
      ...(anterior ? { preco_anterior: anterior } : {}),
      ...(imagem ? { imagem } : {}),
      adicionado_em: porUrl.get(url) ?? agoraIso,
    })
  }
  return out.slice(0, 50)
}

/** Extrai linhas do HTML de /mais-vendidos (mesmo formato da fila). */
export function extrairLinhasDeMaisVendidosHtml(html: string): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  const marcadores = [...html.matchAll(/"best_sellers_configuration"\s*:\s*\{\s*"category"\s*:\s*"([^"]+)"/g)]
  for (let i = 0; i < marcadores.length; i += 1) {
    const start = marcadores[i].index ?? 0
    const end = i + 1 < marcadores.length ? (marcadores[i + 1].index ?? html.length) : html.length
    const trecho = html.slice(start, end)
    const polycardsAt = trecho.search(/"polycards"\s*:\s*/)
    if (polycardsAt < 0) continue
    const after = trecho.slice(polycardsAt).replace(/^"polycards"\s*:\s*/, '')
    let depth = 0
    let endIdx = -1
    for (let k = 0; k < after.length; k += 1) {
      const ch = after[k]
      if (ch === '[') depth += 1
      else if (ch === ']') {
        depth -= 1
        if (depth === 0) {
          endIdx = k
          break
        }
      }
    }
    if (endIdx < 0) continue
    let cards: unknown
    try {
      cards = JSON.parse(after.slice(0, endIdx + 1))
    } catch {
      continue
    }
    if (!Array.isArray(cards)) continue
    for (const card of cards) {
      if (!card || typeof card !== 'object') continue
      const meta = (card as { metadata?: Record<string, unknown> }).metadata ?? {}
      let url = String(meta.url ?? '').trim()
      if (url && !url.startsWith('http')) url = `https://${url.replace(/^\/+/, '')}`
      const id = String(meta.id ?? (url.match(MLB_RE)?.[0] ?? ''))
      if (!url || !id || seen.has(id)) continue
      let titulo = ''
      let atual: number | null = null
      let anterior: number | null = null
      const components = (card as { components?: Array<Record<string, unknown>> }).components ?? []
      for (const comp of components) {
        if (comp.type === 'title') {
          const title = comp.title as { text?: string } | undefined
          titulo = String(title?.text ?? '').trim()
        }
        if (comp.type === 'price') {
          const price = comp.price as {
            current_price?: { value?: number }
            price_labels?: Array<{ values?: Array<{ price?: { previous?: boolean; value?: number } }> }>
          }
          const cur = price?.current_price?.value
          if (typeof cur === 'number') atual = cur
          for (const label of price?.price_labels ?? []) {
            for (const val of label.values ?? []) {
              const p = val.price
              if (p?.previous && typeof p.value === 'number') anterior = p.value
            }
          }
        }
      }
      const tracks = meta.tracks as { price?: { price?: number } } | undefined
      if (atual == null && typeof tracks?.price?.price === 'number') atual = tracks.price.price
      if (!titulo || atual == null) continue
      const pics = ((card as { pictures?: { pictures?: Array<{ id?: string }> } }).pictures?.pictures) ?? []
      const picId = pics[0]?.id
      const imagem = picId ? `https://http2.mlstatic.com/D_NQ_NP_${picId}-O.webp` : ''
      seen.add(id)
      const parts = [url, titulo, String(atual)]
      if (anterior != null || imagem) parts.push(anterior != null ? String(anterior) : '')
      if (imagem) parts.push(imagem)
      out.push(parts.join(' | '))
    }
  }
  return out.slice(0, 50)
}

/** Corpo do bookmarklet (sem o prefixo javascript:). */
export const PRODUTOS_MELI_BOOKMARKLET_SOURCE = `(()=>{try{const h=document.documentElement.innerHTML;const out=[];const seen={};const marc=[...h.matchAll(/"best_sellers_configuration"\\s*:\\s*\\{\\s*"category"\\s*:\\s*"([^"]+)"/g)];const pushCard=(card)=>{const meta=card&&card.metadata||{};let url=(meta.url||"").trim();if(url&&!url.startsWith("http"))url="https://"+url.replace(/^\\/+/,"");const id=String(meta.id||((url.match(/MLB-?\\d+/i)||[])[0]||""));if(!url||!id||seen[id])return;let titulo="",atual=null,ant=null;(card.components||[]).forEach(c=>{if(c.type==="title")titulo=((c.title||{}).text||"").trim();if(c.type==="price"){const cur=((c.price||{}).current_price||{}).value;if(typeof cur==="number")atual=cur;((c.price&&c.price.price_labels)||[]).forEach(l=>{(l.values||[]).forEach(v=>{const p=v.price||{};if(p.previous&&typeof p.value==="number")ant=p.value;});});}});if(atual==null&&meta.tracks&&meta.tracks.price&&typeof meta.tracks.price.price==="number")atual=meta.tracks.price.price;if(!titulo||atual==null)return;const pics=((card.pictures||{}).pictures)||[];const img=pics[0]&&pics[0].id?("https://http2.mlstatic.com/D_NQ_NP_"+pics[0].id+"-O.webp"):"";seen[id]=1;const parts=[url,titulo,String(atual)];if(ant!=null||img)parts.push(ant!=null?String(ant):"");if(img)parts.push(img);out.push(parts.join(" | "));};for(let i=0;i<marc.length;i++){const start=marc[i].index||0;const end=i+1<marc.length?(marc[i+1].index||h.length):h.length;const trecho=h.slice(start,end);const at=trecho.search(/"polycards"\\s*:\\s*/);if(at<0)continue;const after=trecho.slice(at).replace(/^"polycards"\\s*:\\s*/,"");let depth=0,endIdx=-1;for(let k=0;k<after.length;k++){const ch=after[k];if(ch==="[")depth++;else if(ch==="]"){depth--;if(depth===0){endIdx=k;break;}}}if(endIdx<0)continue;let cards;try{cards=JSON.parse(after.slice(0,endIdx+1));}catch{continue;}if(!Array.isArray(cards))continue;cards.forEach(pushCard);}if(!out.length){alert("Nenhum produto encontrado. Abra /mais-vendidos logado e tente de novo.");return;}const text=out.slice(0,50).join("\\n");const ok=()=>alert(out.length+" produto(s) copiados. Cole na fila do bot Nina.");if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(ok).catch(()=>prompt("Copie a fila:",text));}else{prompt("Copie a fila:",text);}}catch(err){alert("Bookmarklet falhou: "+err);}})();`

export function produtosMeliBookmarkletHref(): string {
  return `javascript:${PRODUTOS_MELI_BOOKMARKLET_SOURCE}`
}
