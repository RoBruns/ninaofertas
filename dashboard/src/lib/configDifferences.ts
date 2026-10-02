import type { Bot } from '../api/management'

export function configDifferences(current: Pick<Bot, 'settings' | 'message_template'>, next: Pick<Bot, 'settings' | 'message_template'>) {
  const differences: { path: string; before: unknown; after: unknown }[] = []
  const visit = (before: unknown, after: unknown, path: string) => {
    if (path === 'settings.attribution') return
    const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
    if (object(before) && object(after)) {
      for (const key of [...new Set([...Object.keys(before), ...Object.keys(after)])].sort()) visit(before[key], after[key], `${path}.${key}`)
    } else if (JSON.stringify(before) !== JSON.stringify(after)) differences.push({ path, before, after })
  }
  visit(current.settings, next.settings, 'settings')
  visit(current.message_template, next.message_template, 'message_template')
  return differences
}
