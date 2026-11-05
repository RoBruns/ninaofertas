import {
  DndContext,
  DragOverlay,
  PointerSensor,
  closestCorners,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckSquare, MessageSquare, Plus, SquareKanban, Trash2 } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { api, apiFailure } from '../api/client'
import type { components } from '../api/schema'
import { ConfirmButton, Field, Modal } from '../components/Management'
import { Spinner } from '../components/Spinner'
import { useToast } from '../components/useToast'

type BoardSummary = components['schemas']['TaskBoardSummary']
type BoardDetail = components['schemas']['TaskBoardDetail']
type CardSummary = components['schemas']['TaskCardSummary']
type Label = components['schemas']['TaskLabelResponse']
type Priority = 'low' | 'normal' | 'high'

const priorityLabel: Record<Priority, string> = { low: 'Baixa', normal: 'Normal', high: 'Alta' }

function labelMap(labels: Label[]) {
  return Object.fromEntries(labels.map((label) => [label.id, label]))
}

function KanbanCard({
  card,
  labels,
  onOpen,
}: {
  card: CardSummary
  labels: Record<string, Label>
  onOpen: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: card.id,
    data: { type: 'card', card },
  })
  return (
    <article
      ref={setNodeRef}
      className={`kanban-card${isDragging ? ' dragging' : ''}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      {...attributes}
      {...listeners}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen()
        }
      }}
      role="button"
      tabIndex={0}
    >
      {card.label_ids.length > 0 && (
        <div className="kanban-card-labels">
          {card.label_ids.map((id) => {
            const label = labels[id]
            return label ? (
              <span key={id} className="kanban-label" style={{ background: label.color }} title={label.name} />
            ) : null
          })}
        </div>
      )}
      <strong>{card.title}</strong>
      <div className="kanban-card-meta">
        {card.due_on && <span>{card.due_on}</span>}
        {card.priority !== 'normal' && <span className={`priority-${card.priority}`}>{priorityLabel[card.priority]}</span>}
        {card.checklist_total > 0 && (
          <span>
            <CheckSquare size={12} /> {card.checklist_done}/{card.checklist_total}
          </span>
        )}
        {card.comment_count > 0 && (
          <span>
            <MessageSquare size={12} /> {card.comment_count}
          </span>
        )}
      </div>
    </article>
  )
}

function KanbanColumn({
  list,
  labels,
  onOpenCard,
  onAddCard,
}: {
  list: BoardDetail['lists'][number]
  labels: Record<string, Label>
  onOpenCard: (cardId: string) => void
  onAddCard: (listId: string, title: string) => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: list.id, data: { type: 'list', list } })
  const [draft, setDraft] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const title = draft.trim()
    if (!title) return
    onAddCard(list.id, title)
    setDraft('')
  }
  return (
    <section className={`kanban-column${isOver ? ' over' : ''}`}>
      <header>
        <h2>{list.name}</h2>
        <small>{list.cards.length}</small>
      </header>
      <div ref={setNodeRef} className="kanban-column-body">
        <SortableContext items={list.cards.map((card) => card.id)} strategy={verticalListSortingStrategy}>
          {list.cards.map((card) => (
            <KanbanCard key={card.id} card={card} labels={labels} onOpen={() => onOpenCard(card.id)} />
          ))}
        </SortableContext>
      </div>
      <form className="kanban-add-card" onSubmit={submit}>
        <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Novo cartão" />
        <button className="button ghost" type="submit" disabled={!draft.trim()}>
          <Plus size={16} />
        </button>
      </form>
    </section>
  )
}

function CardDetailForm({
  boardId,
  cardId,
  detail,
  boardLabels,
  onClose,
  invalidate,
}: {
  boardId: string
  cardId: string
  detail: components['schemas']['TaskCardDetail']
  boardLabels: Label[]
  onClose: () => void
  invalidate: () => Promise<void>
}) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [title, setTitle] = useState(detail.title)
  const [description, setDescription] = useState(detail.description || '')
  const [dueOn, setDueOn] = useState(detail.due_on || '')
  const [priority, setPriority] = useState<Priority>(detail.priority)
  const [selectedLabels, setSelectedLabels] = useState<string[]>(detail.label_ids)
  const [comment, setComment] = useState('')
  const [checklistTitle, setChecklistTitle] = useState('')
  const [itemDrafts, setItemDrafts] = useState<Record<string, string>>({})

  const save = useMutation({
    mutationFn: async () => {
      const result = await api.PATCH('/api/task-boards/cards/{card_id}', {
        params: { path: { card_id: cardId } },
        body: {
          title,
          description: description || null,
          due_on: dueOn || null,
          priority,
        },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      const labels = await api.PUT('/api/task-boards/cards/{card_id}/labels', {
        params: { path: { card_id: cardId } },
        body: { label_ids: selectedLabels },
      })
      if (!labels.data) throw apiFailure(labels.error, labels.response)
      return labels.data
    },
    onSuccess: async () => {
      await invalidate()
      showToast('Cartão salvo.', 'success')
    },
    onError: (error) => showToast(error instanceof Error ? error.message : 'Falha ao salvar.', 'error'),
  })

  const archive = useMutation({
    mutationFn: async () => {
      const result = await api.DELETE('/api/task-boards/cards/{card_id}', {
        params: { path: { card_id: cardId } },
      })
      if (result.response.status !== 204) throw apiFailure(result.error, result.response)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['task-board', boardId] })
      showToast('Cartão arquivado.', 'success')
      onClose()
    },
    onError: (error) => showToast(error instanceof Error ? error.message : 'Falha ao arquivar.', 'error'),
  })

  const addComment = useMutation({
    mutationFn: async () => {
      const result = await api.POST('/api/task-boards/cards/{card_id}/comments', {
        params: { path: { card_id: cardId } },
        body: { body: comment },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    onSuccess: async () => {
      setComment('')
      await invalidate()
    },
    onError: (error) => showToast(error instanceof Error ? error.message : 'Falha ao comentar.', 'error'),
  })

  const addChecklist = useMutation({
    mutationFn: async () => {
      const result = await api.POST('/api/task-boards/cards/{card_id}/checklists', {
        params: { path: { card_id: cardId } },
        body: { title: checklistTitle },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    onSuccess: async () => {
      setChecklistTitle('')
      await invalidate()
    },
    onError: (error) => showToast(error instanceof Error ? error.message : 'Falha ao criar checklist.', 'error'),
  })

  const addItem = useMutation({
    mutationFn: async ({ checklistId, title: itemTitle }: { checklistId: string; title: string }) => {
      const result = await api.POST('/api/task-boards/checklists/{checklist_id}/items', {
        params: { path: { checklist_id: checklistId } },
        body: { title: itemTitle },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    onSuccess: async (_data, variables) => {
      setItemDrafts((current) => ({ ...current, [variables.checklistId]: '' }))
      await invalidate()
    },
  })

  const toggleItem = useMutation({
    mutationFn: async ({ itemId, done }: { itemId: string; done: boolean }) => {
      const result = await api.PATCH('/api/task-boards/checklist-items/{item_id}', {
        params: { path: { item_id: itemId } },
        body: { done },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    onSuccess: async () => {
      await invalidate()
    },
  })

  const createLabel = useMutation({
    mutationFn: async (name: string) => {
      const result = await api.POST('/api/task-boards/{board_id}/labels', {
        params: { path: { board_id: boardId } },
        body: { name, color: '#0f766e' },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    onSuccess: async (label) => {
      setSelectedLabels((current) => [...current, label.id])
      await queryClient.invalidateQueries({ queryKey: ['task-board', boardId] })
      await invalidate()
    },
  })

  return (
    <div className="kanban-detail">
      <div className="kanban-detail-main">
        <Field label="Título">
          <input value={title} onChange={(event) => setTitle(event.target.value)} />
        </Field>
        <Field label="Descrição">
          <textarea rows={5} value={description} onChange={(event) => setDescription(event.target.value)} />
        </Field>
        <div className="form-grid columns">
          <Field label="Prazo">
            <input type="date" value={dueOn} onChange={(event) => setDueOn(event.target.value)} />
          </Field>
          <Field label="Prioridade">
            <select value={priority} onChange={(event) => setPriority(event.target.value as Priority)}>
              <option value="low">Baixa</option>
              <option value="normal">Normal</option>
              <option value="high">Alta</option>
            </select>
          </Field>
        </div>
        <div className="kanban-section">
          <h3>Etiquetas</h3>
          <div className="kanban-label-picker">
            {boardLabels.map((label) => {
              const active = selectedLabels.includes(label.id)
              return (
                <button
                  key={label.id}
                  type="button"
                  className={`kanban-label-chip${active ? ' active' : ''}`}
                  style={{ ['--label-color' as string]: label.color }}
                  onClick={() =>
                    setSelectedLabels((current) =>
                      active ? current.filter((id) => id !== label.id) : [...current, label.id],
                    )
                  }
                >
                  {label.name}
                </button>
              )
            })}
            <button
              type="button"
              className="button ghost"
              onClick={() => {
                const name = window.prompt('Nome da etiqueta')
                if (name?.trim()) createLabel.mutate(name.trim())
              }}
            >
              Nova etiqueta
            </button>
          </div>
        </div>
        <div className="kanban-section">
          <h3>Checklists</h3>
          {detail.checklists.map((checklist) => (
            <div key={checklist.id} className="kanban-checklist">
              <strong>{checklist.title}</strong>
              <ul>
                {checklist.items.map((item) => (
                  <li key={item.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={item.done}
                        onChange={(event) => toggleItem.mutate({ itemId: item.id, done: event.target.checked })}
                      />
                      <span className={item.done ? 'done' : ''}>{item.title}</span>
                    </label>
                  </li>
                ))}
              </ul>
              <form
                className="kanban-inline-form"
                onSubmit={(event) => {
                  event.preventDefault()
                  const value = (itemDrafts[checklist.id] || '').trim()
                  if (!value) return
                  addItem.mutate({ checklistId: checklist.id, title: value })
                }}
              >
                <input
                  value={itemDrafts[checklist.id] || ''}
                  onChange={(event) =>
                    setItemDrafts((current) => ({ ...current, [checklist.id]: event.target.value }))
                  }
                  placeholder="Novo item"
                />
                <button className="button ghost" type="submit">
                  Adicionar
                </button>
              </form>
            </div>
          ))}
          <form
            className="kanban-inline-form"
            onSubmit={(event) => {
              event.preventDefault()
              if (!checklistTitle.trim()) return
              addChecklist.mutate()
            }}
          >
            <input
              value={checklistTitle}
              onChange={(event) => setChecklistTitle(event.target.value)}
              placeholder="Nova checklist"
            />
            <button className="button ghost" type="submit">
              Criar
            </button>
          </form>
        </div>
        <div className="kanban-section">
          <h3>Comentários</h3>
          <ul className="kanban-comments">
            {detail.comments.map((entry) => (
              <li key={entry.id}>
                <strong>{entry.author_name || 'Usuário'}</strong>
                <p>{entry.body}</p>
                <small>{new Date(entry.created_at).toLocaleString('pt-BR')}</small>
              </li>
            ))}
          </ul>
          <form
            className="kanban-inline-form"
            onSubmit={(event) => {
              event.preventDefault()
              if (!comment.trim()) return
              addComment.mutate()
            }}
          >
            <input value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Escrever comentário" />
            <button className="button ghost" type="submit">
              Comentar
            </button>
          </form>
        </div>
      </div>
      <div className="form-actions">
        <ConfirmButton question="Arquivar este cartão?" onConfirm={() => archive.mutate()}>
          <Trash2 size={16} /> Arquivar
        </ConfirmButton>
        <button className="button ghost" type="button" onClick={onClose}>
          Fechar
        </button>
        <button className="button primary" type="button" disabled={save.isPending || !title.trim()} onClick={() => save.mutate()}>
          Salvar
        </button>
      </div>
    </div>
  )
}

function CardDetailModal({
  boardId,
  cardId,
  boardLabels,
  onClose,
}: {
  boardId: string
  cardId: string
  boardLabels: Label[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['task-board', boardId] }),
      queryClient.invalidateQueries({ queryKey: ['task-card', cardId] }),
    ])
  }
  const card = useQuery({
    queryKey: ['task-card', cardId],
    queryFn: async () => {
      const result = await api.GET('/api/task-boards/cards/{card_id}', {
        params: { path: { card_id: cardId } },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
  })
  return (
    <Modal title={card.data?.title || 'Cartão'} onClose={onClose} size="wide">
      {card.isLoading || !card.data ? (
        <Spinner label="Carregando cartão" />
      ) : (
        <CardDetailForm
          key={card.data.id}
          boardId={boardId}
          cardId={cardId}
          detail={card.data}
          boardLabels={boardLabels}
          onClose={onClose}
          invalidate={invalidate}
        />
      )}
    </Modal>
  )
}

function findCard(board: BoardDetail, cardId: string) {
  for (const list of board.lists) {
    const card = list.cards.find((item) => item.id === cardId)
    if (card) return { list, card }
  }
  return null
}

export function Tasks() {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [boardId, setBoardId] = useState<string | null>(null)
  const [creatingBoard, setCreatingBoard] = useState(false)
  const [boardName, setBoardName] = useState('')
  const [listName, setListName] = useState('')
  const [openCardId, setOpenCardId] = useState<string | null>(null)
  const [activeCard, setActiveCard] = useState<CardSummary | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  const boards = useQuery({
    queryKey: ['task-boards'],
    queryFn: async () => {
      const result = await api.GET('/api/task-boards')
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
  })

  const selectedId = boardId || boards.data?.[0]?.id || null

  const board = useQuery({
    queryKey: ['task-board', selectedId],
    enabled: !!selectedId,
    queryFn: async () => {
      const result = await api.GET('/api/task-boards/{board_id}', {
        params: { path: { board_id: selectedId! } },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
  })

  const labels = useMemo(() => labelMap(board.data?.labels || []), [board.data?.labels])

  const createBoard = useMutation({
    mutationFn: async () => {
      const result = await api.POST('/api/task-boards', { body: { name: boardName } })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['task-boards'] })
      setBoardId(created.id)
      setCreatingBoard(false)
      setBoardName('')
      showToast('Quadro criado.', 'success')
    },
    onError: (error) => showToast(error instanceof Error ? error.message : 'Falha ao criar quadro.', 'error'),
  })

  const createList = useMutation({
    mutationFn: async () => {
      const result = await api.POST('/api/task-boards/{board_id}/lists', {
        params: { path: { board_id: selectedId! } },
        body: { name: listName },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    onSuccess: async () => {
      setListName('')
      await queryClient.invalidateQueries({ queryKey: ['task-board', selectedId] })
    },
    onError: (error) => showToast(error instanceof Error ? error.message : 'Falha ao criar lista.', 'error'),
  })

  const createCard = useMutation({
    mutationFn: async ({ listId, title }: { listId: string; title: string }) => {
      const result = await api.POST('/api/task-boards/{board_id}/cards', {
        params: { path: { board_id: selectedId! } },
        body: { list_id: listId, title, priority: 'normal' },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['task-board', selectedId] })
    },
    onError: (error) => showToast(error instanceof Error ? error.message : 'Falha ao criar cartão.', 'error'),
  })

  const moveCard = useMutation({
    mutationFn: async ({ cardId, listId, position }: { cardId: string; listId: string; position: number }) => {
      const result = await api.POST('/api/task-boards/cards/{card_id}/move', {
        params: { path: { card_id: cardId } },
        body: { list_id: listId, position },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    onError: (error) => {
      showToast(error instanceof Error ? error.message : 'Falha ao mover cartão.', 'error')
      void queryClient.invalidateQueries({ queryKey: ['task-board', selectedId] })
    },
  })

  const archiveBoard = useMutation({
    mutationFn: async () => {
      const result = await api.DELETE('/api/task-boards/{board_id}', {
        params: { path: { board_id: selectedId! } },
      })
      if (result.response.status !== 204) throw apiFailure(result.error, result.response)
    },
    onSuccess: async () => {
      setBoardId(null)
      await queryClient.invalidateQueries({ queryKey: ['task-boards'] })
      showToast('Quadro arquivado.', 'success')
    },
  })

  const onDragStart = (event: DragStartEvent) => {
    const card = event.active.data.current?.card as CardSummary | undefined
    setActiveCard(card || null)
  }

  const onDragOver = (event: DragOverEvent) => {
    const { active, over } = event
    if (!board.data || !over) return
    const activeId = String(active.id)
    const overId = String(over.id)
    if (activeId === overId) return

    queryClient.setQueryData<BoardDetail>(['task-board', selectedId], (current) => {
      if (!current) return current
      const from = findCard(current, activeId)
      if (!from) return current
      const overList =
        current.lists.find((list) => list.id === overId) ||
        findCard(current, overId)?.list ||
        null
      if (!overList) return current
      if (from.list.id === overList.id) return current

      const lists = current.lists.map((list) => ({ ...list, cards: [...list.cards] }))
      const source = lists.find((list) => list.id === from.list.id)!
      const target = lists.find((list) => list.id === overList.id)!
      source.cards = source.cards.filter((card) => card.id !== activeId)
      const overIndex = target.cards.findIndex((card) => card.id === overId)
      const moved = { ...from.card, list_id: target.id }
      if (overIndex < 0) target.cards.push(moved)
      else target.cards.splice(overIndex, 0, moved)
      return { ...current, lists }
    })
  }

  const onDragEnd = (event: DragEndEvent) => {
    setActiveCard(null)
    const { active, over } = event
    if (!board.data || !over) {
      void queryClient.invalidateQueries({ queryKey: ['task-board', selectedId] })
      return
    }
    const activeId = String(active.id)
    const overId = String(over.id)
    const current = queryClient.getQueryData<BoardDetail>(['task-board', selectedId])
    if (!current) return
    const located = findCard(current, activeId)
    if (!located) return
    const position = located.list.cards.findIndex((card) => card.id === activeId)
    if (position < 0) return
    moveCard.mutate({ cardId: activeId, listId: located.list.id, position })
    if (activeId === overId && located.card.list_id === located.list.id) return
  }

  if (boards.isLoading) return <Spinner label="Carregando tarefas" />

  return (
    <section className="kanban-page">
      <div className="page-heading">
        <div>
          <h1>Tarefas</h1>
          <p>Seu quadro pessoal — colunas, cartões, etiquetas, checklists e comentários.</p>
        </div>
        <div className="kanban-heading-actions">
          <select
            value={selectedId || ''}
            onChange={(event) => setBoardId(event.target.value || null)}
            aria-label="Selecionar quadro"
          >
            {(boards.data || []).map((item: BoardSummary) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <button className="button ghost" type="button" onClick={() => setCreatingBoard(true)}>
            <Plus /> Novo quadro
          </button>
          {selectedId && (
            <ConfirmButton question="Arquivar este quadro?" onConfirm={() => archiveBoard.mutate()}>
              Arquivar quadro
            </ConfirmButton>
          )}
        </div>
      </div>

      {board.isLoading || !board.data ? (
        <Spinner label="Carregando quadro" />
      ) : (
        <>
          <form
            className="kanban-toolbar"
            onSubmit={(event) => {
              event.preventDefault()
              if (!listName.trim()) return
              createList.mutate()
            }}
          >
            <input value={listName} onChange={(event) => setListName(event.target.value)} placeholder="Nova lista" />
            <button className="button ghost" type="submit" disabled={!listName.trim()}>
              Adicionar lista
            </button>
          </form>

          <DndContext
            sensors={sensors}
            collisionDetection={closestCorners}
            onDragStart={onDragStart}
            onDragOver={onDragOver}
            onDragEnd={onDragEnd}
          >
            <div className="kanban-board">
              {board.data.lists.map((list) => (
                <KanbanColumn
                  key={list.id}
                  list={list}
                  labels={labels}
                  onOpenCard={setOpenCardId}
                  onAddCard={(listId, title) => createCard.mutate({ listId, title })}
                />
              ))}
            </div>
            <DragOverlay>
              {activeCard ? (
                <article className="kanban-card overlay">
                  <strong>{activeCard.title}</strong>
                </article>
              ) : null}
            </DragOverlay>
          </DndContext>
        </>
      )}

      {creatingBoard && (
        <Modal title="Novo quadro" onClose={() => setCreatingBoard(false)}>
          <form
            className="form-grid"
            onSubmit={(event) => {
              event.preventDefault()
              if (!boardName.trim()) return
              createBoard.mutate()
            }}
          >
            <Field label="Nome">
              <input required value={boardName} onChange={(event) => setBoardName(event.target.value)} placeholder="Meu quadro" />
            </Field>
            <div className="form-actions">
              <button className="button ghost" type="button" onClick={() => setCreatingBoard(false)}>
                Cancelar
              </button>
              <button className="button primary" type="submit" disabled={createBoard.isPending}>
                Criar
              </button>
            </div>
          </form>
        </Modal>
      )}

      {openCardId && selectedId && (
        <CardDetailModal
          boardId={selectedId}
          cardId={openCardId}
          boardLabels={board.data?.labels || []}
          onClose={() => setOpenCardId(null)}
        />
      )}

      {boards.isSuccess && !boards.data.length && (
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">
            <SquareKanban />
          </span>
          <h2>Nenhum quadro ainda</h2>
          <p>Crie o primeiro para organizar suas tarefas.</p>
        </div>
      )}
    </section>
  )
}
