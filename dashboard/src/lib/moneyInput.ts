export function normalizeMoneyInput(input: string): { value?: string; error?: string } {
  const raw = input.trim()
  if (raw.startsWith('-')) return { error: 'O valor não pode ser negativo.' }
  if (!/^\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?$/.test(raw) && !/^\d+(?:,\d{1,2})?$/.test(raw)) return { error: 'Digite um valor válido, como 1.234,56 ou 1234,56.' }
  const normalized = raw.replaceAll('.', '').replace(',', '.')
  const [integer, decimals = ''] = normalized.split('.')
  return { value: `${integer.replace(/^0+(?=\d)/, '')}.${`${decimals}00`.slice(0, 2)}` }
}

function decimalCents(value: string): bigint {
  const negative = value.startsWith('-')
  const [integer, decimals = ''] = value.replace(/^-/, '').split('.')
  const magnitude = BigInt(integer) * 100n + BigInt(`${decimals}00`.slice(0, 2))
  return negative ? -magnitude : magnitude
}

export function addDecimalStrings(left: string, right: string): string {
  const total = decimalCents(left) + decimalCents(right)
  const negative = total < 0n
  const magnitude = negative ? -total : total
  return `${negative ? '-' : ''}${magnitude / 100n}.${String(magnitude % 100n).padStart(2, '0')}`
}

export function compareDecimalStrings(left: string, right: string): number {
  const a = decimalCents(left), b = decimalCents(right)
  return a < b ? -1 : a > b ? 1 : 0
}
