import { createBrowserRouter } from 'react-router-dom'
import { RequireAuth } from './auth/RequireAuth'
import { Layout } from './components/Layout'
import { Login } from './pages/Login'
import { Overview } from './pages/Overview'
import { Placeholder } from './pages/Placeholder'

const placeholders = [
  ['bots', 'Bots'], ['contas', 'Contas'], ['telefones-grupos', 'Telefones e grupos'],
  ['vendas', 'Vendas'], ['despesas', 'Despesas'], ['campanhas', 'Campanhas'],
  ['alertas', 'Alertas'], ['logs', 'Logs técnicos'], ['auditoria', 'Auditoria'], ['usuarios', 'Usuários'],
].map(([path, title]) => ({ path, element: <Placeholder title={title} /> }))

export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  { element: <RequireAuth />, children: [{ element: <Layout />, children: [{ index: true, element: <Overview /> }, ...placeholders] }] },
])
