const NO_DATA = 'sem dados'

const HEALTH_TEXT: Readonly<Record<string, string>> = {
  ok: 'Sem problemas',
  warning: 'Requer atenção',
  error: 'Com erro',
}

export function healthText(status: string | null | undefined, message: string | null | undefined): string {
  return message || HEALTH_TEXT[status || 'unknown'] || 'Saúde desconhecida'
}

export function formatBRL(value: string | null | undefined): string {
  if (value === null || value === undefined) return NO_DATA
  const match = value.trim().match(/^(-?)(\d+)(?:\.(\d+))?$/)
  if (!match) return NO_DATA
  const [, sign, rawInteger, rawDecimals = ''] = match
  const integer = rawInteger.replace(/^0+(?=\d)/, '').replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  const decimals = `${rawDecimals}00`.slice(0, 2)
  return `${sign ? '-' : ''}R$ ${integer},${decimals}`
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return NO_DATA
  return new Intl.NumberFormat('pt-BR', { style: 'percent', maximumFractionDigits: 1, minimumFractionDigits: 1 }).format(value)
}

export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined) return NO_DATA
  return `${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1, minimumFractionDigits: 1 }).format(value)}x`
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return NO_DATA
  return new Intl.NumberFormat('pt-BR').format(value)
}

export function formatChange(value: number | null | undefined): string {
  if (value === null || value === undefined) return NO_DATA
  const sign = value > 0 ? '+' : ''
  return `${sign}${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1, minimumFractionDigits: 1 }).format(value)}%`
}

export function formatDate(value: string | Date | null | undefined): string {
  if (value === null || value === undefined) return NO_DATA
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return NO_DATA
  return new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo' }).format(date)
}

export function isNegativeMoney(value: string | null | undefined): boolean {
  return value?.trim().startsWith('-') ?? false
}
