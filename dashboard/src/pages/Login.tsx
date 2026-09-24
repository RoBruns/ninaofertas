import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import { Spinner } from '../components/Spinner'
import { BrandMark } from '../components/BrandMark'
import { Price } from '../components/Price'

export function Login() {
  const { login, status } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (status === 'loading') return <Spinner fullScreen label="Restaurando sessão" />
  if (status === 'authenticated') return <Navigate replace to="/" />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(email, password)
      const requested = params.get('next')
      navigate(requested?.startsWith('/') && !requested.startsWith('//') ? requested : '/', { replace: true })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Não foi possível entrar.')
    } finally {
      setSubmitting(false)
    }
  }

  return <main className="login-page"><section className="login-panel"><div className="login-brand"><BrandMark /><div><strong>Nina</strong><small>Central de ofertas</small></div></div><div><h1>Bom te ver de novo</h1><p className="muted">Veja o que a vó encontrou e cuide da operação em um só lugar.</p></div><form onSubmit={submit}><label>E-mail<input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label><label>Senha<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <div className="form-error" role="alert">{error}</div>}<button className="button primary login-button" disabled={submitting}>{submitting ? 'Entrando…' : 'Entrar'}</button></form></section><aside className="login-art" aria-hidden="true"><figure><span className="tag-string" /><div className="price-tag"><span>A vó achou mais uma!</span><Price value="R$ 49,90" /></div><figcaption>Oferta boa não espera.</figcaption></figure></aside></main>
}
