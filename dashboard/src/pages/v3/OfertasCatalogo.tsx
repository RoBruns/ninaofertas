import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PageHeader } from '../../components/v3/PageHeader'
import { Spinner } from '../../components/Spinner'
import { errorMessage } from '../../api/management'
import { v3api } from '../../v3/api'

type Offer = {
  id: number
  nome: string
  preco: string | null
  preco_anterior: string | null
  loja: string | null
  url: string | null
  imagem: string | null
  categoria: string | null
}

type Page = { items: Offer[]; total: number }

function money(value: string | null) {
  if (!value) return '—'
  const n = Number(value)
  if (Number.isNaN(n) || n <= 0) return '—'
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

export function OfertasCatalogo() {
  const [q, setQ] = useState('')
  const [loja, setLoja] = useState('')
  const offers = useQuery({
    queryKey: ['v3-offers', q, loja],
    queryFn: () => {
      const params = new URLSearchParams({ page_size: '48' })
      if (q.trim()) params.set('q', q.trim())
      if (loja.trim()) params.set('loja', loja.trim())
      return v3api.get<Page>(`/api/v3/offers?${params}`)
    },
  })
  return (
    <div>
      <PageHeader
        eyebrow="Catálogo"
        title="Ofertas"
        description="Catálogo do espelho, das fontes (Promobit/RSS) e dos envios. Filtre por loja ou nome."
        actions={
          <>
            <input placeholder="Buscar" value={q} onChange={(e) => setQ(e.target.value)} />
            <input placeholder="Loja" value={loja} onChange={(e) => setLoja(e.target.value)} />
          </>
        }
      />
      {offers.isLoading && <Spinner label="Carregando ofertas" />}
      {offers.isError && <div className="page-error">{errorMessage(offers.error)}</div>}
      <div className="v3-grid">
        {(offers.data?.items ?? []).map((offer) => (
          <article className="v3-card" key={offer.id}>
            {offer.imagem ? (
              <img className="v3-card-media" src={offer.imagem} alt="" />
            ) : (
              <div className="v3-card-media" />
            )}
            <div className="v3-card-body">
              {offer.loja && <span className="v3-chip">{offer.loja}</span>}
              {offer.categoria === 'fonte' ? <span className="v3-chip">fonte</span> : null}
              <h3>{offer.nome}</h3>
              <div className="v3-price">
                {offer.preco_anterior ? <s>{money(offer.preco_anterior)}</s> : null}
                {money(offer.preco)}
              </div>
              {offer.url ? (
                <a className="button ghost" href={offer.url} target="_blank" rel="noreferrer">
                  Abrir link
                </a>
              ) : null}
            </div>
          </article>
        ))}
      </div>
      {!offers.isLoading && !(offers.data?.items.length) && (
        <p className="muted">
          Nenhuma oferta ainda. Em Fontes, ligue Promobit/RSS e clique em Sincronizar — ou espere o
          espelho da Nina 1.
        </p>
      )}
    </div>
  )
}
