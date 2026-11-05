import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ToastProvider } from '../components/Toast'
import { Tasks } from './Tasks'

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderTasks() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <Tasks />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('mostra o quadro seed com listas e cartão', async () => {
  const boardId = '11111111-1111-1111-1111-111111111111'
  const listId = '22222222-2222-2222-2222-222222222222'
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo) => {
      const request = input instanceof Request ? input : new Request(String(input))
      const path = new URL(request.url).pathname
      if (path === '/api/task-boards') {
        return json([
          {
            id: boardId,
            name: 'Meu quadro',
            position: 0,
            archived_at: null,
            created_at: '2026-11-02T12:00:00Z',
            updated_at: '2026-11-02T12:00:00Z',
          },
        ])
      }
      if (path === `/api/task-boards/${boardId}`) {
        return json({
          id: boardId,
          name: 'Meu quadro',
          position: 0,
          archived_at: null,
          created_at: '2026-11-02T12:00:00Z',
          updated_at: '2026-11-02T12:00:00Z',
          labels: [],
          lists: [
            {
              id: listId,
              name: 'A fazer',
              position: 0,
              archived_at: null,
              cards: [
                {
                  id: '33333333-3333-3333-3333-333333333333',
                  list_id: listId,
                  title: 'Revisar cookie ML',
                  description: null,
                  position: 0,
                  due_on: null,
                  priority: 'normal',
                  archived_at: null,
                  label_ids: [],
                  checklist_total: 0,
                  checklist_done: 0,
                  comment_count: 0,
                },
              ],
            },
            {
              id: '44444444-4444-4444-4444-444444444444',
              name: 'Em andamento',
              position: 1,
              archived_at: null,
              cards: [],
            },
            {
              id: '55555555-5555-5555-5555-555555555555',
              name: 'Feito',
              position: 2,
              archived_at: null,
              cards: [],
            },
          ],
        })
      }
      return json({ error: { code: 'NOT_FOUND', message: path } }, 404)
    }),
  )

  renderTasks()

  expect(await screen.findByRole('heading', { name: 'Tarefas' })).toBeInTheDocument()
  expect(await screen.findByText('Revisar cookie ML')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'A fazer' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Em andamento' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Feito' })).toBeInTheDocument()
})
