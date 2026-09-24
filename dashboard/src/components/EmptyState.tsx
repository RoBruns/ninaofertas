import { Inbox, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
export function EmptyState({ title, description, action, icon: Icon = Inbox }: { title: string; description?: string; action?: ReactNode; icon?: LucideIcon }) { return <section className="empty-state"><span className="empty-icon" aria-hidden="true"><Icon /></span><h2>{title}</h2>{description && <p>{description}</p>}{action}</section> }
