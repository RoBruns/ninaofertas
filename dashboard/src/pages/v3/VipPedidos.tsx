import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageHeader } from '../../components/v3/PageHeader'
import { Drawer } from '../../components/v3/Drawer'
import { Spinner } from '../../components/Spinner'
import { Field } from '../../components/Management'
import { useToast } from '../../components/useToast'
import { errorMessage } from '../../api/management'
import { v3api } from '../../v3/api'

type Vip = {
  id: string
  contact_name: string
  contact_phone: string | null
  wish_product: string
  max_price: string
  status: string
  matched_offer_id: number | null
}

export function VipPedidos() {
  const { showToast } = useToast()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [wish, setWish] = useState('')
  const [maxPrice, setMaxPrice] = useState('100')
  const list = useQuery({
    queryKey: ['v3-vip'],
    queryFn: () => v3api.get<Vip[]>('/api/v3/vip'),
  })
  const create = useMutation({
    mutationFn: () =>
      v3api.post('/api/v3/vip', {
        contact_name: name,
        contact_phone: phone || null,
        wish_product: wish,
        max_price: maxPrice,
      }),
    onSuccess: async () => {
      setOpen(false)
      setName('')
      setPhone('')
      setWish('')
      await qc.invalidateQueries({ queryKey: ['v3-vip'] })
      showToast('Pedido VIP criado.', 'success')
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })
  const match = useMutation({
    mutationFn: () => v3api.post<Vip[]>('/api/v3/vip/match'),
    onSuccess: async (rows) => {
      await qc.invalidateQueries({ queryKey: ['v3-vip'] })
      showToast(rows.length ? `${rows.length} match(es).` : 'Nenhum match agora.', 'success')
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })
  if (list.isLoading) return <Spinner label="Carregando VIP" />
  return (
    <div>
      <PageHeader
        eyebrow="Radar"
        title="Pedidos VIP"
        description="Wishlist com teto de preço. Match contra o catálogo recente."
        actions={
          <>
            <button className="button ghost" type="button" disabled={match.isPending} onClick={() => match.mutate()}>
              Rodar match
            </button>
            <button className="button primary" type="button" onClick={() => setOpen(true)}>
              Novo pedido
            </button>
          </>
        }
      />
      <div className="v3-grid">
        {(list.data ?? []).map((v) => (
          <article className="v3-card" key={v.id}>
            <div className="v3-card-body">
              <span className="v3-chip">{v.status}</span>
              <h3>{v.wish_product}</h3>
              <p className="muted">{v.contact_name}{v.contact_phone ? ` · ${v.contact_phone}` : ''}</p>
              <div className="v3-price">até R$ {v.max_price}</div>
              {v.matched_offer_id != null && <small>Oferta #{v.matched_offer_id}</small>}
            </div>
          </article>
        ))}
      </div>
      {!list.data?.length && <p className="muted">Nenhum pedido VIP.</p>}
      {open && (
        <Drawer title="Novo pedido VIP" onClose={() => setOpen(false)}>
          <form
            className="form-grid"
            onSubmit={(e) => {
              e.preventDefault()
              create.mutate()
            }}
          >
            <Field label="Contato"><input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Telefone"><input value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
            <Field label="Produto desejado"><input required value={wish} onChange={(e) => setWish(e.target.value)} /></Field>
            <Field label="Preço máximo"><input required type="number" step="0.01" value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} /></Field>
            <button className="button primary" disabled={create.isPending}>Salvar</button>
          </form>
        </Drawer>
      )}
    </div>
  )
}
