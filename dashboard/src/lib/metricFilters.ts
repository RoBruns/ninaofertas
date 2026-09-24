export type Preset = 'today' | '7d' | '30d' | 'month' | 'previous_month' | 'custom'

export function localDate(date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function shiftDate(date: Date, days: number) { return new Date(date.getTime() + days * 86_400_000) }

export function presetDates(preset: Preset, now = new Date()): { from: string; to: string } {
  const today = localDate(now)
  const [year, month] = today.split('-').map(Number)
  if (preset === 'today') return { from: today, to: today }
  if (preset === '7d') return { from: localDate(shiftDate(now, -6)), to: today }
  if (preset === 'month') return { from: `${year}-${String(month).padStart(2, '0')}-01`, to: today }
  if (preset === 'previous_month') return { from: localDate(new Date(Date.UTC(year, month - 2, 1, 12))), to: localDate(new Date(Date.UTC(year, month - 1, 0, 12))) }
  return { from: localDate(shiftDate(now, -29)), to: today }
}
