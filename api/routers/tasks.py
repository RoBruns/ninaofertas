"""Kanban pessoal de tarefas por usuário."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from api.audit import record_audit
from api.deps import get_current_user, get_db, limit_authenticated_write
from api.errors import APIError
from api.ratelimit import client_ip
from api.schemas.tasks import (
    ReorderPayload,
    TaskBoardCreate,
    TaskBoardDetail,
    TaskBoardSummary,
    TaskBoardUpdate,
    TaskCardCreate,
    TaskCardDetail,
    TaskCardLabelsUpdate,
    TaskCardMove,
    TaskCardSummary,
    TaskCardUpdate,
    TaskChecklistCreate,
    TaskChecklistItemCreate,
    TaskChecklistItemResponse,
    TaskChecklistItemUpdate,
    TaskChecklistResponse,
    TaskChecklistUpdate,
    TaskCommentCreate,
    TaskCommentResponse,
    TaskLabelCreate,
    TaskLabelResponse,
    TaskLabelUpdate,
    TaskListCreate,
    TaskListResponse,
    TaskListUpdate,
)
from core.models import (
    TaskBoard,
    TaskCard,
    TaskChecklist,
    TaskChecklistItem,
    TaskComment,
    TaskLabel,
    TaskList,
    User,
)

router = APIRouter(prefix="/task-boards", tags=["tasks"])
CurrentUser = Annotated[User, Depends(get_current_user)]
Db = Annotated[Session, Depends(get_db)]

DEFAULT_LISTS = ("A fazer", "Em andamento", "Feito")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _board_query(owner_id: UUID, user_id: UUID):
    return select(TaskBoard).where(
        TaskBoard.owner_id == owner_id,
        TaskBoard.user_id == user_id,
        TaskBoard.archived_at.is_(None),
    )


def _owned_board(session: Session, board_id: UUID, user: User) -> TaskBoard:
    board = session.scalar(
        select(TaskBoard).where(
            TaskBoard.id == board_id,
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
            TaskBoard.archived_at.is_(None),
        )
    )
    if board is None:
        raise APIError(404, "NOT_FOUND", "Quadro não encontrado")
    return board


def _load_board(session: Session, board_id: UUID, user: User) -> TaskBoard:
    board = session.scalar(
        select(TaskBoard)
        .where(
            TaskBoard.id == board_id,
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
            TaskBoard.archived_at.is_(None),
        )
        .options(
            selectinload(TaskBoard.labels),
            selectinload(TaskBoard.lists)
            .selectinload(TaskList.cards)
            .selectinload(TaskCard.labels),
            selectinload(TaskBoard.lists)
            .selectinload(TaskList.cards)
            .selectinload(TaskCard.comments),
            selectinload(TaskBoard.lists)
            .selectinload(TaskList.cards)
            .selectinload(TaskCard.checklists)
            .selectinload(TaskChecklist.items),
        )
    )
    if board is None:
        raise APIError(404, "NOT_FOUND", "Quadro não encontrado")
    return board


def _owned_list(session: Session, list_id: UUID, user: User) -> TaskList:
    task_list = session.scalar(
        select(TaskList)
        .join(TaskBoard, TaskList.board_id == TaskBoard.id)
        .where(
            TaskList.id == list_id,
            TaskList.archived_at.is_(None),
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
            TaskBoard.archived_at.is_(None),
        )
    )
    if task_list is None:
        raise APIError(404, "NOT_FOUND", "Lista não encontrada")
    return task_list


def _owned_card(session: Session, card_id: UUID, user: User) -> TaskCard:
    card = session.scalar(
        select(TaskCard)
        .join(TaskList, TaskCard.list_id == TaskList.id)
        .join(TaskBoard, TaskList.board_id == TaskBoard.id)
        .where(
            TaskCard.id == card_id,
            TaskCard.archived_at.is_(None),
            TaskList.archived_at.is_(None),
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
            TaskBoard.archived_at.is_(None),
        )
        .options(
            selectinload(TaskCard.labels),
            selectinload(TaskCard.comments),
            selectinload(TaskCard.checklists).selectinload(TaskChecklist.items),
        )
    )
    if card is None:
        raise APIError(404, "NOT_FOUND", "Cartão não encontrado")
    return card


def _seed_board(session: Session, user: User) -> TaskBoard:
    board = TaskBoard(
        id=uuid4(),
        owner_id=user.tenant_id,
        user_id=user.id,
        name="Meu quadro",
        position=0,
    )
    session.add(board)
    session.flush()
    for index, name in enumerate(DEFAULT_LISTS):
        session.add(
            TaskList(id=uuid4(), board_id=board.id, name=name, position=index)
        )
    session.flush()
    return board


def _card_summary(card: TaskCard) -> TaskCardSummary:
    total = sum(len(checklist.items) for checklist in card.checklists)
    done = sum(1 for checklist in card.checklists for item in checklist.items if item.done)
    return TaskCardSummary(
        id=card.id,
        list_id=card.list_id,
        title=card.title,
        description=card.description,
        position=card.position,
        due_on=card.due_on,
        priority=card.priority,  # type: ignore[arg-type]
        archived_at=card.archived_at,
        label_ids=[label.id for label in card.labels],
        checklist_total=total,
        checklist_done=done,
        comment_count=len(card.comments),
    )


def _author_names(session: Session, comments: list[TaskComment]) -> dict[UUID, str | None]:
    ids = {comment.author_id for comment in comments}
    if not ids:
        return {}
    rows = session.execute(select(User.id, User.name).where(User.id.in_(ids))).all()
    return {row.id: row.name for row in rows}


def _card_detail(session: Session, card: TaskCard) -> TaskCardDetail:
    names = _author_names(session, list(card.comments))
    summary = _card_summary(card)
    return TaskCardDetail(
        **summary.model_dump(),
        labels=[TaskLabelResponse(id=label.id, name=label.name, color=label.color) for label in card.labels],
        comments=[
            TaskCommentResponse(
                id=comment.id,
                author_id=comment.author_id,
                author_name=names.get(comment.author_id),
                body=comment.body,
                created_at=comment.created_at,
            )
            for comment in card.comments
        ],
        checklists=[
            TaskChecklistResponse(
                id=checklist.id,
                title=checklist.title,
                position=checklist.position,
                items=[
                    TaskChecklistItemResponse(
                        id=item.id,
                        title=item.title,
                        done=item.done,
                        position=item.position,
                    )
                    for item in checklist.items
                ],
            )
            for checklist in card.checklists
        ],
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _board_summary(board: TaskBoard) -> TaskBoardSummary:
    return TaskBoardSummary(
        id=board.id,
        name=board.name,
        position=board.position,
        archived_at=board.archived_at,
        created_at=board.created_at,
        updated_at=board.updated_at,
    )


def _board_detail(session: Session, board: TaskBoard) -> TaskBoardDetail:
    lists = sorted(
        (item for item in board.lists if item.archived_at is None),
        key=lambda item: item.position,
    )
    return TaskBoardDetail(
        **_board_summary(board).model_dump(),
        lists=[
            TaskListResponse(
                id=task_list.id,
                name=task_list.name,
                position=task_list.position,
                archived_at=task_list.archived_at,
                cards=[
                    _card_summary(card)
                    for card in sorted(
                        (card for card in task_list.cards if card.archived_at is None),
                        key=lambda card: card.position,
                    )
                ],
            )
            for task_list in lists
        ],
        labels=[
            TaskLabelResponse(id=label.id, name=label.name, color=label.color)
            for label in sorted(board.labels, key=lambda label: label.name)
        ],
    )


def _touch_board(board: TaskBoard) -> None:
    board.updated_at = _now()


def _shift_positions(
    session: Session,
    *,
    model,
    parent_field: str,
    parent_id: UUID,
    from_position: int,
    exclude_id: UUID | None = None,
) -> None:
    statement = select(model).where(
        getattr(model, parent_field) == parent_id,
        model.position >= from_position,
        model.archived_at.is_(None) if hasattr(model, "archived_at") else True,
    )
    if exclude_id is not None:
        statement = statement.where(model.id != exclude_id)
    for item in session.scalars(statement.order_by(model.position.desc())):
        item.position += 1


# --- Boards -----------------------------------------------------------------


@router.get("", response_model=list[TaskBoardSummary])
def list_boards(user: CurrentUser, session: Db) -> list[TaskBoardSummary]:
    boards = list(
        session.scalars(_board_query(user.tenant_id, user.id).order_by(TaskBoard.position.asc()))
    )
    if not boards:
        board = _seed_board(session, user)
        record_audit(
            session,
            user,
            "task_board",
            str(board.id),
            "create",
            None,
            {"name": board.name, "seed": True},
            None,
        )
        session.commit()
        boards = [board]
    return [_board_summary(board) for board in boards]


@router.post(
    "",
    response_model=TaskBoardDetail,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_board(
    payload: TaskBoardCreate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskBoardDetail:
    position = session.scalar(
        select(func.coalesce(func.max(TaskBoard.position), -1)).where(
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
            TaskBoard.archived_at.is_(None),
        )
    )
    board = TaskBoard(
        id=uuid4(),
        owner_id=user.tenant_id,
        user_id=user.id,
        name=payload.name.strip(),
        position=int(position or -1) + 1,
    )
    session.add(board)
    session.flush()
    for index, name in enumerate(DEFAULT_LISTS):
        session.add(TaskList(id=uuid4(), board_id=board.id, name=name, position=index))
    session.flush()
    loaded = _load_board(session, board.id, user)
    response = _board_detail(session, loaded)
    record_audit(
        session,
        user,
        "task_board",
        str(board.id),
        "create",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.get("/{board_id}", response_model=TaskBoardDetail)
def get_board(board_id: UUID, user: CurrentUser, session: Db) -> TaskBoardDetail:
    return _board_detail(session, _load_board(session, board_id, user))


@router.patch(
    "/{board_id}",
    response_model=TaskBoardSummary,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_board(
    board_id: UUID,
    payload: TaskBoardUpdate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskBoardSummary:
    board = _owned_board(session, board_id, user)
    before = _board_summary(board).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name") is None and "name" in changes:
        raise APIError(422, "VALIDATION_ERROR", "name não aceita null")
    if "name" in changes:
        board.name = changes["name"].strip()
    if "position" in changes and changes["position"] is not None:
        board.position = changes["position"]
    if changes.get("archived") is True:
        board.archived_at = _now()
    _touch_board(board)
    response = _board_summary(board)
    record_audit(
        session,
        user,
        "task_board",
        str(board.id),
        "update",
        before,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.delete(
    "/{board_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_board(
    board_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> None:
    board = _owned_board(session, board_id, user)
    before = _board_summary(board).model_dump(mode="json")
    board.archived_at = _now()
    _touch_board(board)
    record_audit(
        session,
        user,
        "task_board",
        str(board.id),
        "archive",
        before,
        None,
        client_ip(request),
    )
    session.commit()


# --- Lists ------------------------------------------------------------------


@router.post(
    "/{board_id}/lists",
    response_model=TaskListResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_list(
    board_id: UUID,
    payload: TaskListCreate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskListResponse:
    board = _owned_board(session, board_id, user)
    position = session.scalar(
        select(func.coalesce(func.max(TaskList.position), -1)).where(
            TaskList.board_id == board.id,
            TaskList.archived_at.is_(None),
        )
    )
    task_list = TaskList(
        id=uuid4(),
        board_id=board.id,
        name=payload.name.strip(),
        position=int(position or -1) + 1,
    )
    session.add(task_list)
    _touch_board(board)
    session.flush()
    response = TaskListResponse(
        id=task_list.id,
        name=task_list.name,
        position=task_list.position,
        archived_at=task_list.archived_at,
        cards=[],
    )
    record_audit(
        session,
        user,
        "task_list",
        str(task_list.id),
        "create",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.patch(
    "/lists/{list_id}",
    response_model=TaskListResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_list(
    list_id: UUID,
    payload: TaskListUpdate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskListResponse:
    task_list = _owned_list(session, list_id, user)
    before = {
        "id": str(task_list.id),
        "name": task_list.name,
        "position": task_list.position,
    }
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name") is None and "name" in changes:
        raise APIError(422, "VALIDATION_ERROR", "name não aceita null")
    if "name" in changes:
        task_list.name = changes["name"].strip()
    if "position" in changes and changes["position"] is not None:
        task_list.position = changes["position"]
    if changes.get("archived") is True:
        task_list.archived_at = _now()
    board = session.get(TaskBoard, task_list.board_id)
    if board is not None:
        _touch_board(board)
    response = TaskListResponse(
        id=task_list.id,
        name=task_list.name,
        position=task_list.position,
        archived_at=task_list.archived_at,
        cards=[],
    )
    record_audit(
        session,
        user,
        "task_list",
        str(task_list.id),
        "update",
        before,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.post(
    "/lists/reorder",
    response_model=list[TaskListResponse],
    dependencies=[Depends(limit_authenticated_write)],
)
def reorder_lists(
    payload: ReorderPayload,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> list[TaskListResponse]:
    lists = [_owned_list(session, item.id, user) for item in payload.items]
    board_ids = {task_list.board_id for task_list in lists}
    if len(board_ids) != 1:
        raise APIError(422, "VALIDATION_ERROR", "Todas as listas devem ser do mesmo quadro")
    by_id = {item.id: item.position for item in payload.items}
    for task_list in lists:
        task_list.position = by_id[task_list.id]
    board = session.get(TaskBoard, next(iter(board_ids)))
    if board is not None:
        _touch_board(board)
    record_audit(
        session,
        user,
        "task_list",
        str(next(iter(board_ids))),
        "reorder",
        None,
        {"items": [item.model_dump(mode="json") for item in payload.items]},
        client_ip(request),
    )
    session.commit()
    return [
        TaskListResponse(
            id=task_list.id,
            name=task_list.name,
            position=task_list.position,
            archived_at=task_list.archived_at,
            cards=[],
        )
        for task_list in sorted(lists, key=lambda item: item.position)
    ]


@router.delete(
    "/lists/{list_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_list(
    list_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> None:
    task_list = _owned_list(session, list_id, user)
    before = {"id": str(task_list.id), "name": task_list.name}
    task_list.archived_at = _now()
    board = session.get(TaskBoard, task_list.board_id)
    if board is not None:
        _touch_board(board)
    record_audit(
        session,
        user,
        "task_list",
        str(task_list.id),
        "archive",
        before,
        None,
        client_ip(request),
    )
    session.commit()


# --- Cards ------------------------------------------------------------------


@router.post(
    "/{board_id}/cards",
    response_model=TaskCardSummary,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_card(
    board_id: UUID,
    payload: TaskCardCreate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskCardSummary:
    board = _owned_board(session, board_id, user)
    task_list = _owned_list(session, payload.list_id, user)
    if task_list.board_id != board.id:
        raise APIError(422, "VALIDATION_ERROR", "Lista não pertence a este quadro")
    position = session.scalar(
        select(func.coalesce(func.max(TaskCard.position), -1)).where(
            TaskCard.list_id == task_list.id,
            TaskCard.archived_at.is_(None),
        )
    )
    card = TaskCard(
        id=uuid4(),
        list_id=task_list.id,
        title=payload.title.strip(),
        description=payload.description,
        due_on=payload.due_on,
        priority=payload.priority,
        position=int(position or -1) + 1,
    )
    session.add(card)
    _touch_board(board)
    session.flush()
    card = _owned_card(session, card.id, user)
    response = _card_summary(card)
    record_audit(
        session,
        user,
        "task_card",
        str(card.id),
        "create",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.get("/cards/{card_id}", response_model=TaskCardDetail)
def get_card(card_id: UUID, user: CurrentUser, session: Db) -> TaskCardDetail:
    return _card_detail(session, _owned_card(session, card_id, user))


@router.patch(
    "/cards/{card_id}",
    response_model=TaskCardDetail,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_card(
    card_id: UUID,
    payload: TaskCardUpdate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskCardDetail:
    card = _owned_card(session, card_id, user)
    before = _card_summary(card).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("title") is None and "title" in changes:
        raise APIError(422, "VALIDATION_ERROR", "title não aceita null")
    if "title" in changes:
        card.title = changes["title"].strip()
    if "description" in changes:
        card.description = changes["description"]
    if "due_on" in changes:
        card.due_on = changes["due_on"]
    if "priority" in changes and changes["priority"] is not None:
        card.priority = changes["priority"]
    if changes.get("archived") is True:
        card.archived_at = _now()
    card.updated_at = _now()
    board = session.scalar(
        select(TaskBoard)
        .join(TaskList, TaskList.board_id == TaskBoard.id)
        .where(TaskList.id == card.list_id)
    )
    if board is not None:
        _touch_board(board)
    response = _card_detail(session, card)
    record_audit(
        session,
        user,
        "task_card",
        str(card.id),
        "update",
        before,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.post(
    "/cards/{card_id}/move",
    response_model=TaskCardSummary,
    dependencies=[Depends(limit_authenticated_write)],
)
def move_card(
    card_id: UUID,
    payload: TaskCardMove,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskCardSummary:
    card = _owned_card(session, card_id, user)
    target = _owned_list(session, payload.list_id, user)
    source_board = session.scalar(
        select(TaskBoard)
        .join(TaskList, TaskList.board_id == TaskBoard.id)
        .where(TaskList.id == card.list_id)
    )
    if source_board is None or target.board_id != source_board.id:
        raise APIError(422, "VALIDATION_ERROR", "Não é possível mover para outro quadro")
    before = {"list_id": str(card.list_id), "position": card.position}
    _shift_positions(
        session,
        model=TaskCard,
        parent_field="list_id",
        parent_id=target.id,
        from_position=payload.position,
        exclude_id=card.id,
    )
    card.list_id = target.id
    card.position = payload.position
    card.updated_at = _now()
    _touch_board(source_board)
    session.flush()
    card = _owned_card(session, card.id, user)
    response = _card_summary(card)
    record_audit(
        session,
        user,
        "task_card",
        str(card.id),
        "move",
        before,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.delete(
    "/cards/{card_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_card(
    card_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> None:
    card = _owned_card(session, card_id, user)
    before = _card_summary(card).model_dump(mode="json")
    card.archived_at = _now()
    card.updated_at = _now()
    board = session.scalar(
        select(TaskBoard)
        .join(TaskList, TaskList.board_id == TaskBoard.id)
        .where(TaskList.id == card.list_id)
    )
    if board is not None:
        _touch_board(board)
    record_audit(
        session,
        user,
        "task_card",
        str(card.id),
        "archive",
        before,
        None,
        client_ip(request),
    )
    session.commit()


# --- Labels -----------------------------------------------------------------


@router.post(
    "/{board_id}/labels",
    response_model=TaskLabelResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_label(
    board_id: UUID,
    payload: TaskLabelCreate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskLabelResponse:
    board = _owned_board(session, board_id, user)
    existing = session.scalar(
        select(TaskLabel.id).where(
            TaskLabel.board_id == board.id, TaskLabel.name == payload.name.strip()
        )
    )
    if existing is not None:
        raise APIError(409, "CONFLICT", "Já existe uma etiqueta com este nome")
    label = TaskLabel(
        id=uuid4(),
        board_id=board.id,
        name=payload.name.strip(),
        color=payload.color,
    )
    session.add(label)
    _touch_board(board)
    session.flush()
    response = TaskLabelResponse(id=label.id, name=label.name, color=label.color)
    record_audit(
        session,
        user,
        "task_label",
        str(label.id),
        "create",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.patch(
    "/labels/{label_id}",
    response_model=TaskLabelResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_label(
    label_id: UUID,
    payload: TaskLabelUpdate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskLabelResponse:
    label = session.scalar(
        select(TaskLabel)
        .join(TaskBoard, TaskLabel.board_id == TaskBoard.id)
        .where(
            TaskLabel.id == label_id,
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
            TaskBoard.archived_at.is_(None),
        )
    )
    if label is None:
        raise APIError(404, "NOT_FOUND", "Etiqueta não encontrada")
    before = TaskLabelResponse(id=label.id, name=label.name, color=label.color).model_dump()
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        name = changes["name"].strip()
        clash = session.scalar(
            select(TaskLabel.id).where(
                TaskLabel.board_id == label.board_id,
                TaskLabel.name == name,
                TaskLabel.id != label.id,
            )
        )
        if clash is not None:
            raise APIError(409, "CONFLICT", "Já existe uma etiqueta com este nome")
        label.name = name
    if "color" in changes and changes["color"] is not None:
        label.color = changes["color"]
    board = session.get(TaskBoard, label.board_id)
    if board is not None:
        _touch_board(board)
    response = TaskLabelResponse(id=label.id, name=label.name, color=label.color)
    record_audit(
        session,
        user,
        "task_label",
        str(label.id),
        "update",
        before,
        response.model_dump(),
        client_ip(request),
    )
    session.commit()
    return response


@router.delete(
    "/labels/{label_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_label(
    label_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> None:
    label = session.scalar(
        select(TaskLabel)
        .join(TaskBoard, TaskLabel.board_id == TaskBoard.id)
        .where(
            TaskLabel.id == label_id,
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
            TaskBoard.archived_at.is_(None),
        )
    )
    if label is None:
        raise APIError(404, "NOT_FOUND", "Etiqueta não encontrada")
    before = TaskLabelResponse(id=label.id, name=label.name, color=label.color).model_dump()
    board = session.get(TaskBoard, label.board_id)
    session.delete(label)
    if board is not None:
        _touch_board(board)
    record_audit(
        session,
        user,
        "task_label",
        str(label_id),
        "delete",
        before,
        None,
        client_ip(request),
    )
    session.commit()


@router.put(
    "/cards/{card_id}/labels",
    response_model=TaskCardDetail,
    dependencies=[Depends(limit_authenticated_write)],
)
def set_card_labels(
    card_id: UUID,
    payload: TaskCardLabelsUpdate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskCardDetail:
    card = _owned_card(session, card_id, user)
    board = session.scalar(
        select(TaskBoard)
        .join(TaskList, TaskList.board_id == TaskBoard.id)
        .where(TaskList.id == card.list_id)
    )
    if board is None:
        raise APIError(404, "NOT_FOUND", "Quadro não encontrado")
    if payload.label_ids:
        labels = list(
            session.scalars(
                select(TaskLabel).where(
                    TaskLabel.board_id == board.id,
                    TaskLabel.id.in_(payload.label_ids),
                )
            )
        )
        if len(labels) != len(set(payload.label_ids)):
            raise APIError(422, "VALIDATION_ERROR", "Uma ou mais etiquetas são inválidas")
    else:
        labels = []
    card.labels = labels
    card.updated_at = _now()
    _touch_board(board)
    response = _card_detail(session, card)
    record_audit(
        session,
        user,
        "task_card",
        str(card.id),
        "labels",
        None,
        {"label_ids": [str(item) for item in payload.label_ids]},
        client_ip(request),
    )
    session.commit()
    return response


# --- Comments ---------------------------------------------------------------


@router.post(
    "/cards/{card_id}/comments",
    response_model=TaskCommentResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_comment(
    card_id: UUID,
    payload: TaskCommentCreate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskCommentResponse:
    card = _owned_card(session, card_id, user)
    comment = TaskComment(
        id=uuid4(),
        card_id=card.id,
        author_id=user.id,
        body=payload.body.strip(),
    )
    session.add(comment)
    card.updated_at = _now()
    session.flush()
    response = TaskCommentResponse(
        id=comment.id,
        author_id=comment.author_id,
        author_name=user.name,
        body=comment.body,
        created_at=comment.created_at,
    )
    record_audit(
        session,
        user,
        "task_comment",
        str(comment.id),
        "create",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.delete(
    "/comments/{comment_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_comment(
    comment_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> None:
    comment = session.scalar(
        select(TaskComment)
        .join(TaskCard, TaskComment.card_id == TaskCard.id)
        .join(TaskList, TaskCard.list_id == TaskList.id)
        .join(TaskBoard, TaskList.board_id == TaskBoard.id)
        .where(
            TaskComment.id == comment_id,
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
        )
    )
    if comment is None:
        raise APIError(404, "NOT_FOUND", "Comentário não encontrado")
    if comment.author_id != user.id:
        raise APIError(403, "FORBIDDEN", "Só o autor pode apagar o comentário")
    before = {"id": str(comment.id), "body": comment.body}
    session.delete(comment)
    record_audit(
        session,
        user,
        "task_comment",
        str(comment_id),
        "delete",
        before,
        None,
        client_ip(request),
    )
    session.commit()


# --- Checklists -------------------------------------------------------------


@router.post(
    "/cards/{card_id}/checklists",
    response_model=TaskChecklistResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_checklist(
    card_id: UUID,
    payload: TaskChecklistCreate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskChecklistResponse:
    card = _owned_card(session, card_id, user)
    position = session.scalar(
        select(func.coalesce(func.max(TaskChecklist.position), -1)).where(
            TaskChecklist.card_id == card.id
        )
    )
    checklist = TaskChecklist(
        id=uuid4(),
        card_id=card.id,
        title=payload.title.strip(),
        position=int(position or -1) + 1,
    )
    session.add(checklist)
    card.updated_at = _now()
    session.flush()
    response = TaskChecklistResponse(
        id=checklist.id, title=checklist.title, position=checklist.position, items=[]
    )
    record_audit(
        session,
        user,
        "task_checklist",
        str(checklist.id),
        "create",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.patch(
    "/checklists/{checklist_id}",
    response_model=TaskChecklistResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_checklist(
    checklist_id: UUID,
    payload: TaskChecklistUpdate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskChecklistResponse:
    checklist = session.scalar(
        select(TaskChecklist)
        .join(TaskCard, TaskChecklist.card_id == TaskCard.id)
        .join(TaskList, TaskCard.list_id == TaskList.id)
        .join(TaskBoard, TaskList.board_id == TaskBoard.id)
        .where(
            TaskChecklist.id == checklist_id,
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
        )
        .options(selectinload(TaskChecklist.items))
    )
    if checklist is None:
        raise APIError(404, "NOT_FOUND", "Checklist não encontrado")
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes and changes["title"] is not None:
        checklist.title = changes["title"].strip()
    if "position" in changes and changes["position"] is not None:
        checklist.position = changes["position"]
    response = TaskChecklistResponse(
        id=checklist.id,
        title=checklist.title,
        position=checklist.position,
        items=[
            TaskChecklistItemResponse(
                id=item.id, title=item.title, done=item.done, position=item.position
            )
            for item in checklist.items
        ],
    )
    record_audit(
        session,
        user,
        "task_checklist",
        str(checklist.id),
        "update",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.delete(
    "/checklists/{checklist_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_checklist(
    checklist_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> None:
    checklist = session.scalar(
        select(TaskChecklist)
        .join(TaskCard, TaskChecklist.card_id == TaskCard.id)
        .join(TaskList, TaskCard.list_id == TaskList.id)
        .join(TaskBoard, TaskList.board_id == TaskBoard.id)
        .where(
            TaskChecklist.id == checklist_id,
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
        )
    )
    if checklist is None:
        raise APIError(404, "NOT_FOUND", "Checklist não encontrado")
    before = {"id": str(checklist.id), "title": checklist.title}
    session.delete(checklist)
    record_audit(
        session,
        user,
        "task_checklist",
        str(checklist_id),
        "delete",
        before,
        None,
        client_ip(request),
    )
    session.commit()


@router.post(
    "/checklists/{checklist_id}/items",
    response_model=TaskChecklistItemResponse,
    status_code=201,
    dependencies=[Depends(limit_authenticated_write)],
)
def create_checklist_item(
    checklist_id: UUID,
    payload: TaskChecklistItemCreate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskChecklistItemResponse:
    checklist = session.scalar(
        select(TaskChecklist)
        .join(TaskCard, TaskChecklist.card_id == TaskCard.id)
        .join(TaskList, TaskCard.list_id == TaskList.id)
        .join(TaskBoard, TaskList.board_id == TaskBoard.id)
        .where(
            TaskChecklist.id == checklist_id,
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
        )
    )
    if checklist is None:
        raise APIError(404, "NOT_FOUND", "Checklist não encontrado")
    position = session.scalar(
        select(func.coalesce(func.max(TaskChecklistItem.position), -1)).where(
            TaskChecklistItem.checklist_id == checklist.id
        )
    )
    item = TaskChecklistItem(
        id=uuid4(),
        checklist_id=checklist.id,
        title=payload.title.strip(),
        position=int(position or -1) + 1,
    )
    session.add(item)
    session.flush()
    response = TaskChecklistItemResponse(
        id=item.id, title=item.title, done=item.done, position=item.position
    )
    record_audit(
        session,
        user,
        "task_checklist_item",
        str(item.id),
        "create",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.patch(
    "/checklist-items/{item_id}",
    response_model=TaskChecklistItemResponse,
    dependencies=[Depends(limit_authenticated_write)],
)
def update_checklist_item(
    item_id: UUID,
    payload: TaskChecklistItemUpdate,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> TaskChecklistItemResponse:
    item = session.scalar(
        select(TaskChecklistItem)
        .join(TaskChecklist, TaskChecklistItem.checklist_id == TaskChecklist.id)
        .join(TaskCard, TaskChecklist.card_id == TaskCard.id)
        .join(TaskList, TaskCard.list_id == TaskList.id)
        .join(TaskBoard, TaskList.board_id == TaskBoard.id)
        .where(
            TaskChecklistItem.id == item_id,
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
        )
    )
    if item is None:
        raise APIError(404, "NOT_FOUND", "Item do checklist não encontrado")
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes and changes["title"] is not None:
        item.title = changes["title"].strip()
    if "done" in changes and changes["done"] is not None:
        item.done = changes["done"]
    if "position" in changes and changes["position"] is not None:
        item.position = changes["position"]
    response = TaskChecklistItemResponse(
        id=item.id, title=item.title, done=item.done, position=item.position
    )
    record_audit(
        session,
        user,
        "task_checklist_item",
        str(item.id),
        "update",
        None,
        response.model_dump(mode="json"),
        client_ip(request),
    )
    session.commit()
    return response


@router.delete(
    "/checklist-items/{item_id}",
    status_code=204,
    dependencies=[Depends(limit_authenticated_write)],
)
def delete_checklist_item(
    item_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Db,
) -> None:
    item = session.scalar(
        select(TaskChecklistItem)
        .join(TaskChecklist, TaskChecklistItem.checklist_id == TaskChecklist.id)
        .join(TaskCard, TaskChecklist.card_id == TaskCard.id)
        .join(TaskList, TaskCard.list_id == TaskList.id)
        .join(TaskBoard, TaskList.board_id == TaskBoard.id)
        .where(
            TaskChecklistItem.id == item_id,
            TaskBoard.owner_id == user.tenant_id,
            TaskBoard.user_id == user.id,
        )
    )
    if item is None:
        raise APIError(404, "NOT_FOUND", "Item do checklist não encontrado")
    before = {"id": str(item.id), "title": item.title}
    session.delete(item)
    record_audit(
        session,
        user,
        "task_checklist_item",
        str(item_id),
        "delete",
        before,
        None,
        client_ip(request),
    )
    session.commit()
