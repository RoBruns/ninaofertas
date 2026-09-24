import { EmptyState } from '../components/EmptyState'

export function Placeholder({ title }: { title: string }) {
  return <section><div className="page-heading"><div><h1>{title}</h1></div></div><EmptyState title="Em construção" description="Esta área estará disponível nas próximas fases do dashboard." /></section>
}
