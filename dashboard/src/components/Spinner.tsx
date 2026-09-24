import clsx from 'clsx'

export function Spinner({ fullScreen = false, label = 'Carregando' }: { fullScreen?: boolean; label?: string }) {
  return (
    <div className={clsx('spinner-wrap', fullScreen && 'spinner-screen')} role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}
