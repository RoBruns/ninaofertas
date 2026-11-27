import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Check,
  Copy,
  Download,
  ImagePlus,
  Link2,
  Palette,
  Plus,
  Radio,
  RotateCcw,
  Save,
  Send,
  Ticket,
  Trash2,
} from 'lucide-react'
import { PageHeader } from '../../components/v3/PageHeader'
import { Drawer } from '../../components/v3/Drawer'
import { Spinner } from '../../components/Spinner'
import { Field } from '../../components/Management'
import { useToast } from '../../components/useToast'
import { errorMessage } from '../../api/management'
import { v3api } from '../../v3/api'
import {
  ESTILOS_LOJA,
  PADRAO_CUPOM_INICIAL,
  limparTextoInterno,
  limparValidadePublica,
  montarLegendaCupom,
  renderizarArteCupomPng,
  type PadraoCupomClient,
} from '../../v3/cupomArte'

type Coupon = {
  id: string
  code: string
  store: string | null
  title: string | null
  url: string | null
  status: string
  source_group_name: string | null
  min_value: string | number
  validity: string | null
  report_count: number
  created_at: string
}

type Destination = {
  id: string
  name: string
  phone_label: string | null
  bot_name: string | null
  whatsapp_id: string
}

const PADRAO_KEY = 'nina-v3-cupom-padrao'
const LOJA_OPTIONS = Object.entries(ESTILOS_LOJA)

function lerPadraoLocal(): PadraoCupomClient {
  try {
    const raw = localStorage.getItem(PADRAO_KEY)
    if (!raw) return { ...PADRAO_CUPOM_INICIAL, linksPorLoja: {} }
    const parsed = JSON.parse(raw) as Partial<PadraoCupomClient>
    return {
      ...PADRAO_CUPOM_INICIAL,
      ...parsed,
      linksPorLoja: { ...(parsed.linksPorLoja || {}) },
    }
  } catch {
    return { ...PADRAO_CUPOM_INICIAL, linksPorLoja: {} }
  }
}

function lojaKey(store: string | null | undefined): string {
  const raw = (store || '').toLowerCase()
  if (raw in ESTILOS_LOJA) return raw
  if (raw.includes('mercado') || raw === 'ml') return 'mercadolivre'
  if (raw.includes('shopee')) return 'shopee'
  if (raw.includes('amazon')) return 'amazon'
  if (raw.includes('ali')) return 'aliexpress'
  if (raw.includes('magalu') || raw.includes('magazine') || raw === 'awin') return 'awin'
  return 'outra'
}

function minNumber(value: string | number | null | undefined): number {
  const n = Number(value ?? 0)
  return Number.isFinite(n) ? n : 0
}

export function RadarCupons() {
  const { showToast } = useToast()
  const qc = useQueryClient()
  const [gavetaNovo, setGavetaNovo] = useState(false)
  const [codigo, setCodigo] = useState('')
  const [loja, setLoja] = useState('mercadolivre')
  const [descricao, setDescricao] = useState('')
  const [valorMin, setValorMin] = useState('0')
  const [validade, setValidade] = useState('Até acabar a verba')
  const [copiadoId, setCopiadoId] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  const [padrao, setPadrao] = useState<PadraoCupomClient>(() => lerPadraoLocal())
  const [cupomDisparo, setCupomDisparo] = useState<Coupon | null>(null)
  const [abaEditor, setAbaEditor] = useState<'mensagem' | 'arte'>('mensagem')
  const [linkCupom, setLinkCupom] = useState('')
  const [mensagemTexto, setMensagemTexto] = useState('')
  const [mensagemEditadaManual, setMensagemEditadaManual] = useState(false)
  const [artePreview, setArtePreview] = useState('')
  const [destinosSel, setDestinosSel] = useState<string[]>([])
  const [padraoSalvoMsg, setPadraoSalvoMsg] = useState<string | null>(null)
  const inputFundoRef = useRef<HTMLInputElement | null>(null)

  const list = useQuery({
    queryKey: ['v3-coupons'],
    queryFn: () => v3api.get<Coupon[]>('/api/v3/coupons'),
    refetchInterval: 15_000,
  })
  const destinos = useQuery({
    queryKey: ['v3-coupon-destinations'],
    queryFn: () => v3api.get<Destination[]>('/api/v3/coupon-destinations'),
  })
  const sources = useQuery({
    queryKey: ['v3-sources'],
    queryFn: () => v3api.get<Array<{ enabled: boolean }>>('/api/v3/sources'),
  })

  const fontesAtivas = useMemo(
    () => (sources.data ?? []).filter((s) => s.enabled).length,
    [sources.data],
  )
  const gruposDestino = destinos.data ?? []

  const create = useMutation({
    mutationFn: () =>
      v3api.post<Coupon>('/api/v3/coupons', {
        code: codigo,
        store: loja,
        title: descricao || null,
        min_value: Number(valorMin) || 0,
        validity: validade || null,
      }),
    onSuccess: async () => {
      setGavetaNovo(false)
      setCodigo('')
      setDescricao('')
      setValorMin('0')
      setValidade('Até acabar a verba')
      setAviso('Cupom adicionado ao Radar.')
      await qc.invalidateQueries({ queryKey: ['v3-coupons'] })
      showToast('Cupom cadastrado.', 'success')
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })

  const patchStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      v3api.patch(`/api/v3/coupons/${id}`, { status }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['v3-coupons'] })
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })

  const remove = useMutation({
    mutationFn: (id: string) => v3api.delete(`/api/v3/coupons/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['v3-coupons'] })
      showToast('Cupom removido.', 'success')
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })

  const disparar = useMutation({
    mutationFn: () => {
      if (!cupomDisparo) throw new Error('Sem cupom')
      return v3api.post<{ ok: boolean; enviados: number; total: number; erro?: string }>(
        `/api/v3/coupons/${cupomDisparo.id}/dispatch`,
        {
          group_ids: destinosSel,
          message: mensagemTexto.trim(),
          image_base64: artePreview || null,
          link: linkCupom.trim() || null,
        },
      )
    },
    onSuccess: (d) => {
      if (d.ok) {
        setAviso(
          `Cupom ${cupomDisparo?.code} enviado com arte para ${d.enviados}/${d.total} grupo(s)!`,
        )
        setCupomDisparo(null)
        showToast('Cupom disparado.', 'success')
      } else {
        showToast(d.erro || 'Falha ao disparar.', 'error')
      }
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })

  useEffect(() => {
    if (!cupomDisparo) return
    let ativo = true
    const key = lojaKey(cupomDisparo.store)
    renderizarArteCupomPng({
      codigo: cupomDisparo.code,
      loja: key,
      arroba: '@ninaofertas',
      valorMinimo: minNumber(cupomDisparo.min_value),
      validade: cupomDisparo.validity || '',
      padrao,
    }).then((dataUrl) => {
      if (ativo) setArtePreview(dataUrl)
    })
    return () => {
      ativo = false
    }
  }, [cupomDisparo, padrao])

  useEffect(() => {
    if (!cupomDisparo || mensagemEditadaManual) return
    setMensagemTexto(
      montarLegendaCupom({
        template: padrao.templateMensagem,
        codigo: cupomDisparo.code,
        loja: lojaKey(cupomDisparo.store),
        link: linkCupom,
        arroba: '@ninaofertas',
        valorMinimo: minNumber(cupomDisparo.min_value),
        validade: cupomDisparo.validity || undefined,
      }),
    )
  }, [cupomDisparo, padrao.templateMensagem, linkCupom, mensagemEditadaManual])

  function abrirDisparo(c: Coupon) {
    const key = lojaKey(c.store)
    const linkInicial = padrao.linksPorLoja?.[key] || c.url || ''
    setCupomDisparo(c)
    setAbaEditor('mensagem')
    setLinkCupom(linkInicial)
    setMensagemEditadaManual(false)
    setPadraoSalvoMsg(null)
    setMensagemTexto(
      montarLegendaCupom({
        template: padrao.templateMensagem,
        codigo: c.code,
        loja: key,
        link: linkInicial,
        arroba: '@ninaofertas',
        valorMinimo: minNumber(c.min_value),
        validade: c.validity || undefined,
      }),
    )
    setDestinosSel(gruposDestino.map((g) => g.id))
  }

  function handleUploadFundo(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = typeof reader.result === 'string' ? reader.result : ''
      if (dataUrl) {
        setPadrao((prev) => ({
          ...prev,
          estilo: 'personalizado',
          fundoDataUrl: dataUrl,
        }))
      }
    }
    reader.readAsDataURL(file)
  }

  function salvarMeuPadrao() {
    const next: PadraoCupomClient = {
      ...padrao,
      linksPorLoja: cupomDisparo
        ? { ...padrao.linksPorLoja, [lojaKey(cupomDisparo.store)]: linkCupom.trim() }
        : padrao.linksPorLoja,
    }
    setPadrao(next)
    localStorage.setItem(PADRAO_KEY, JSON.stringify(next))
    setPadraoSalvoMsg('Padrão de arte e mensagem salvo para os próximos cupons.')
  }

  function restaurarPadrao() {
    const inicial = { ...PADRAO_CUPOM_INICIAL, linksPorLoja: {} }
    setPadrao(inicial)
    setMensagemEditadaManual(false)
    setPadraoSalvoMsg('Padrão restaurado (clique em Salvar para fixar).')
  }

  function copiar(c: Coupon) {
    void navigator.clipboard.writeText(c.code)
    setCopiadoId(c.id)
    window.setTimeout(() => setCopiadoId(null), 1500)
  }

  function baixarArte() {
    if (!artePreview || !cupomDisparo) return
    const a = document.createElement('a')
    a.href = artePreview
    a.download = `cupom-${lojaKey(cupomDisparo.store)}-${cupomDisparo.code}.png`
    a.click()
  }

  if (list.isLoading) return <Spinner label="Carregando cupons" />

  const cupons = list.data ?? []

  return (
    <div className="radar-page">
      <PageHeader
        eyebrow="Radar automático · Cupons"
        title="Radar de Cupons."
        description="Cupons capturados das fontes e do espelho entram aqui prontos para disparar com logo da loja, seu link e seu padrão de arte."
        actions={
          <button className="button primary" type="button" onClick={() => setGavetaNovo(true)}>
            <Plus size={16} /> Novo cupom
          </button>
        }
      />

      <div className="radar-status">
        <Radio size={16} className={fontesAtivas > 0 || gruposDestino.length > 0 ? 'ok' : ''} />
        <span>
          {fontesAtivas > 0 || gruposDestino.length > 0 ? (
            <>
              Captura ativa{fontesAtivas > 0 ? <> em <strong>{fontesAtivas} fonte(s)</strong></> : null}
              {gruposDestino.length > 0 ? (
                <>
                  {fontesAtivas > 0 ? ' · ' : ' '}
                  <strong>{gruposDestino.length} grupo(s)</strong> prontos para disparo
                </>
              ) : null}
              . Clique em <strong>Disparar com arte</strong> para personalizar e enviar.
            </>
          ) : (
            <>
              Nenhuma fonte/grupo ativo ainda. Ligue fontes em{' '}
              <Link to="/fontes">Fontes & Espelho</Link> para capturar cupons automaticamente.
            </>
          )}
        </span>
      </div>

      {aviso && (
        <div className="radar-aviso">
          <Check size={16} />
          <span>{aviso}</span>
        </div>
      )}

      {list.isError && <div className="page-error">{errorMessage(list.error)}</div>}

      {cupons.length === 0 ? (
        <div className="radar-empty">
          <Ticket size={32} />
          <p className="title">Nenhum cupom no radar</p>
          <p className="muted">
            Assim que cair um cupom numa fonte ligada ou no espelho, ele aparece aqui pronto para
            disparar com a logo da loja e seu link.
          </p>
        </div>
      ) : (
        <div className="radar-grid">
          {cupons.map((c) => {
            const key = lojaKey(c.store)
            const est = ESTILOS_LOJA[key] || ESTILOS_LOJA.outra
            const valLimpa = limparValidadePublica(c.validity || '')
            const descInterna = limparTextoInterno(c.title || '')
            const minimo = minNumber(c.min_value)
            return (
              <article className="radar-card" key={c.id}>
                <div className="radar-card-band" style={{ backgroundColor: est.bg, color: est.fg }}>
                  {est.logoUrl ? (
                    <span className={est.precisaPillClaroNoOficial ? 'radar-logo-pill' : ''}>
                      <img src={est.logoUrl} alt={est.nome} />
                    </span>
                  ) : (
                    <span className="radar-store-name">{est.nome}</span>
                  )}
                  <span className={`radar-status-pill ${c.status}`}>{c.status}</span>
                </div>

                <div className="radar-card-main">
                  <button type="button" className="radar-code" onClick={() => copiar(c)} title="Copiar">
                    <span>{c.code}</span>
                    {copiadoId === c.id ? <Check size={16} /> : <Copy size={16} />}
                  </button>
                  <p className="muted">
                    {descInterna || `Cupom ativo para compras na ${est.nome}.`}
                  </p>
                  {(minimo > 0 || valLimpa) && (
                    <div className="radar-meta">
                      {minimo > 0 && <span>Mín. R$ {minimo.toFixed(0)}</span>}
                      {valLimpa && <span>· {valLimpa}</span>}
                    </div>
                  )}
                </div>

                <div className="radar-card-actions">
                  <button type="button" className="button primary" onClick={() => abrirDisparo(c)}>
                    <Send size={14} /> Disparar com arte
                  </button>
                  {c.status !== 'expirado' ? (
                    <button
                      type="button"
                      className="button ghost icon"
                      title="Marcar como expirado"
                      onClick={() => patchStatus.mutate({ id: c.id, status: 'expirado' })}
                    >
                      <AlertTriangle size={14} />
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="button ghost icon"
                      title="Reativar"
                      onClick={() => patchStatus.mutate({ id: c.id, status: 'ativo' })}
                    >
                      <RotateCcw size={14} />
                    </button>
                  )}
                  <button
                    type="button"
                    className="button ghost icon"
                    title="Excluir"
                    onClick={() => remove.mutate(c.id)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      )}

      {cupomDisparo && (
        <Drawer
          title={`Disparar ${cupomDisparo.code}`}
          subtitle="Personalize a arte, o link e o texto — e salve como padrão."
          onClose={() => setCupomDisparo(null)}
        >
          <div className="radar-disparo">
            {artePreview ? (
              <div className="radar-arte-preview">
                <img src={artePreview} alt="Prévia da arte do cupom" />
              </div>
            ) : null}

            <div className="radar-tabs">
              <button
                type="button"
                className={abaEditor === 'mensagem' ? 'on' : ''}
                onClick={() => setAbaEditor('mensagem')}
              >
                <Link2 size={14} /> Link & Mensagem
              </button>
              <button
                type="button"
                className={abaEditor === 'arte' ? 'on' : ''}
                onClick={() => setAbaEditor('arte')}
              >
                <Palette size={14} /> Padrão da Arte
              </button>
            </div>

            {abaEditor === 'mensagem' ? (
              <div className="form-grid">
                <Field label="Link para testar o cupom (seu afiliado)">
                  <input
                    value={linkCupom}
                    onChange={(e) => setLinkCupom(e.target.value)}
                    placeholder="https://www.mercadolivre.com.br/cupons"
                  />
                </Field>
                <Field
                  label={
                    mensagemEditadaManual
                      ? 'Mensagem (editada — voltar ao template)'
                      : 'Mensagem enviada no WhatsApp'
                  }
                >
                  {mensagemEditadaManual ? (
                    <button
                      type="button"
                      className="button ghost"
                      onClick={() => setMensagemEditadaManual(false)}
                    >
                      Voltar ao template
                    </button>
                  ) : null}
                  <textarea
                    rows={5}
                    value={mensagemTexto}
                    onChange={(e) => {
                      setMensagemTexto(e.target.value)
                      setMensagemEditadaManual(true)
                    }}
                    className="font-mono"
                  />
                  <p className="muted tiny">
                    Variáveis: {'{loja}'}, {'{codigo}'}, {'{link}'}, {'{arroba}'}.
                  </p>
                </Field>
              </div>
            ) : (
              <div className="form-grid">
                <Field label="Estilo da arte">
                  <div className="radar-estilo-grid">
                    {(
                      [
                        { id: 'oficial', label: 'Oficial loja' },
                        { id: 'dark', label: 'Dark Impacto' },
                        { id: 'personalizado', label: 'Minha imagem' },
                      ] as const
                    ).map((op) => (
                      <button
                        key={op.id}
                        type="button"
                        className={padrao.estilo === op.id ? 'on' : ''}
                        onClick={() => setPadrao((p) => ({ ...p, estilo: op.id }))}
                      >
                        {op.label}
                      </button>
                    ))}
                  </div>
                </Field>
                {padrao.estilo === 'personalizado' && (
                  <div className="radar-upload">
                    <input
                      ref={inputFundoRef}
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      onChange={handleUploadFundo}
                      hidden
                    />
                    <button
                      type="button"
                      className="button ghost"
                      onClick={() => inputFundoRef.current?.click()}
                    >
                      <ImagePlus size={14} />
                      {padrao.fundoDataUrl ? 'Trocar imagem de fundo' : 'Subir arte base (PNG/JPG)'}
                    </button>
                  </div>
                )}
                <div className="radar-2col">
                  <Field label="Faixa / Título">
                    <input
                      value={padrao.titulo}
                      onChange={(e) => setPadrao((p) => ({ ...p, titulo: e.target.value }))}
                    />
                  </Field>
                  <Field label="Subtítulo">
                    <input
                      value={padrao.subtitulo}
                      onChange={(e) => setPadrao((p) => ({ ...p, subtitulo: e.target.value }))}
                    />
                  </Field>
                </div>
                <Field label="Chamada inferior na arte">
                  <input
                    value={padrao.chamada}
                    onChange={(e) => setPadrao((p) => ({ ...p, chamada: e.target.value }))}
                  />
                </Field>
                <Field label="Template padrão de texto">
                  <textarea
                    rows={4}
                    value={padrao.templateMensagem}
                    onChange={(e) => {
                      setPadrao((p) => ({ ...p, templateMensagem: e.target.value }))
                      setMensagemEditadaManual(false)
                    }}
                    className="font-mono"
                  />
                </Field>
                <label className="radar-check">
                  <input
                    type="checkbox"
                    checked={padrao.mostrarLogoLoja}
                    onChange={(e) =>
                      setPadrao((p) => ({ ...p, mostrarLogoLoja: e.target.checked }))
                    }
                  />
                  Mostrar logo da loja
                </label>
                <label className="radar-check">
                  <input
                    type="checkbox"
                    checked={padrao.mostrarArroba}
                    onChange={(e) =>
                      setPadrao((p) => ({ ...p, mostrarArroba: e.target.checked }))
                    }
                  />
                  Mostrar @ninaofertas na arte
                </label>
              </div>
            )}

            <div className="radar-padrao-bar">
              <button type="button" className="button ghost" onClick={salvarMeuPadrao}>
                <Save size={14} /> Salvar como meu padrão
              </button>
              <button type="button" className="button ghost" onClick={restaurarPadrao}>
                Restaurar padrão
              </button>
            </div>
            {padraoSalvoMsg && <p className="ok-text">{padraoSalvoMsg}</p>}

            <Field label={`Grupos do WhatsApp (${destinosSel.length} selecionados)`}>
              {gruposDestino.length === 0 ? (
                <p className="muted">
                  Cadastre grupos num bot ativo para disparar direto, ou baixe a arte PNG.
                </p>
              ) : (
                <div className="radar-destinos">
                  {gruposDestino.map((g) => {
                    const marcado = destinosSel.includes(g.id)
                    return (
                      <label key={g.id}>
                        <input
                          type="checkbox"
                          checked={marcado}
                          onChange={() =>
                            setDestinosSel((prev) =>
                              prev.includes(g.id)
                                ? prev.filter((x) => x !== g.id)
                                : [...prev, g.id],
                            )
                          }
                        />
                        <span>
                          {g.name}
                          {g.bot_name ? ` · ${g.bot_name}` : ''}
                        </span>
                      </label>
                    )
                  })}
                </div>
              )}
            </Field>

            <div className="radar-send-row">
              <button type="button" className="button ghost" onClick={baixarArte}>
                <Download size={16} /> Baixar PNG
              </button>
              <button
                type="button"
                className="button primary"
                disabled={disparar.isPending || destinosSel.length === 0}
                onClick={() => disparar.mutate()}
              >
                <Send size={16} />
                {disparar.isPending ? 'Enviando…' : 'Enviar nos grupos'}
              </button>
            </div>
          </div>
        </Drawer>
      )}

      {gavetaNovo && (
        <Drawer
          title="Cadastrar cupom"
          subtitle="Adicione manualmente um cupom para disparar com arte."
          onClose={() => setGavetaNovo(false)}
        >
          <form
            className="form-grid"
            onSubmit={(e) => {
              e.preventDefault()
              create.mutate()
            }}
          >
            <Field label="Código do cupom">
              <input
                required
                className="font-mono"
                value={codigo}
                onChange={(e) => setCodigo(e.target.value.toUpperCase())}
                placeholder="Ex: MELI20"
              />
            </Field>
            <Field label="Loja">
              <select value={loja} onChange={(e) => setLoja(e.target.value)}>
                {LOJA_OPTIONS.map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.nome}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Regra / Desconto">
              <input
                value={descricao}
                onChange={(e) => setDescricao(e.target.value)}
                placeholder="Ex: R$ 20 OFF acima de R$ 150"
              />
            </Field>
            <div className="radar-2col">
              <Field label="Mínimo (R$)">
                <input
                  type="number"
                  value={valorMin}
                  onChange={(e) => setValorMin(e.target.value)}
                />
              </Field>
              <Field label="Validade">
                <input value={validade} onChange={(e) => setValidade(e.target.value)} />
              </Field>
            </div>
            <button className="button primary" disabled={create.isPending} type="submit">
              <Plus size={16} /> Salvar cupom
            </button>
          </form>
        </Drawer>
      )}
    </div>
  )
}
