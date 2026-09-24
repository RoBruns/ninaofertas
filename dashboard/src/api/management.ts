import type { components } from './schema'

export type Account = components['schemas']['AccountResponse']
export type AccountCreate = components['schemas']['AccountCreate']
export type Bot = components['schemas']['BotResponse']
export type BotCreate = components['schemas']['BotCreate']
export type BotSettings = components['schemas']['BotSettings-Input']
export type CredentialStatus = components['schemas']['CredentialStatus']
export type Group = components['schemas']['GroupResponse']
export type Niche = components['schemas']['NicheResponse']
export type Phone = components['schemas']['PhoneResponse']
export type Platform = components['schemas']['PlatformResponse']
export type UserResponse = components['schemas']['UserResponse']

export const defaultSettings: BotSettings = {
  schema_version: 1,
  _legacy_input: false,
  filters: {
    preco_minimo: 20, preco_maximo: 5000, desconto_minimo: 15,
    lojas: [], categorias_meli: [], termos_busca: [], palavras_chave: [],
    bloquear_produtos: [], bloquear_termos: [], excecoes_bloqueio: [],
    max_vendas: 20, max_idade_oferta_horas: 0,
  },
  pacing: {
    max_ofertas_por_ciclo: 1, intervalo_minutos_entre_ofertas: 5,
    max_ofertas_por_rajada: 3, janela_rajada_minutos: 15,
    pausa_entre_rajadas_minutos: 35, max_ofertas_por_hora: 6,
    max_ofertas_por_dia: 80, max_ofertas_globais_por_hora: 8,
    max_ofertas_globais_por_dia: 90,
  },
  content: { aceitar_cupons: true, aceitar_campanhas: false, max_cupons_por_dia: 2, baseline_ciclos: 5 },
  schedule: { check_interval: 60, quiet_hours: { start: '23:00', end: '07:00' } },
}

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Não foi possível concluir a solicitação.'
}
