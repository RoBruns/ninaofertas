export function alertDestination(type: string) {
  if (type === 'auth_expired' || type === 'credential_expired') return '/contas'
  if (type.includes('group')) return '/telefones'
  if (type.includes('campaign') || type.includes('cost')) return '/campanhas'
  if (type.includes('bot') || type.includes('automation')) return '/bots'
  return '/alertas'
}
