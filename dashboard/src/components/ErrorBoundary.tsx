import { Component, type ErrorInfo, type ReactNode } from 'react'

type State = { failed: boolean }

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State { return { failed: true } }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (import.meta.env.DEV) console.error(error, info)
  }

  render() {
    if (this.state.failed) {
      return <main className="fatal-error"><h1>Algo deu errado</h1><p>Não foi possível exibir esta página.</p><button className="button primary" onClick={() => window.location.reload()}>Tentar novamente</button></main>
    }
    return this.props.children
  }
}
