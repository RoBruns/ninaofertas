import { Info } from 'lucide-react'

const terms: Record<string, string> = {
  buyer_hash: 'identificação do comprador', cost_per_buyer: 'custo por comprador',
  buyers: 'compradores', clicks: 'cliques', conversion: 'conversão', periodo: 'período',
}

function humanizeWarning(warning: string) {
  return Object.entries(terms).reduce((text, [term, replacement]) => text.replaceAll(term, replacement), warning)
}

export function DataWarnings({ warnings }: { warnings: readonly string[] }) {
  const items = [...new Set(warnings.map(humanizeWarning))]
  if (!items.length) return null
  return <details className="data-notes"><summary><Info aria-hidden="true" />Dados incompletos ({items.length})</summary><ul>{items.map((warning) => <li key={warning}>{warning}</li>)}</ul></details>
}
