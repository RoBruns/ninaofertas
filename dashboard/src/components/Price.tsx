import clsx from 'clsx'

export function Price({ value }: { value: string }) {
  const match = /^(-)?R\$\s([\d.]+),(\d{2})$/.exec(value)
  if (!match) return <span className="price-plain">{value}</span>
  return <span className={clsx('price', match[1] && 'negative')} aria-label={value}>
    {match[1] && <span className="price-sign" aria-hidden="true">−</span>}
    <span className="price-cur" aria-hidden="true">R$</span>
    <span className="price-int" aria-hidden="true">{match[2]}</span>
    <span className="price-cents" aria-hidden="true">,{match[3]}</span>
  </span>
}
