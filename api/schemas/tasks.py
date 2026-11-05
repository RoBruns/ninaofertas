"""Schemas do kanban pessoal de tarefas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Priority = Literal["low", "normal", "high"]


class TaskBoardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TaskBoardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    position: int | None = None
    archived: bool | None = None


class TaskBoardSummary(BaseModel):
    id: UUID
    name: str
    position: int
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TaskLabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#64748b", pattern=r"^#[0-9A-Fa-f]{6}$")


class TaskLabelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class TaskLabelResponse(BaseModel):
    id: UUID
    name: str
    color: str


class TaskListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TaskListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    position: int | None = None
    archived: bool | None = None


class TaskCardCreate(BaseModel):
    list_id: UUID
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10_000)
    due_on: date | None = None
    priority: Priority = "normal"


class TaskCardUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10_000)
    due_on: date | None = None
    priority: Priority | None = None
    archived: bool | None = None


class TaskCardMove(BaseModel):
    list_id: UUID
    position: int = Field(ge=0)


class ReorderItem(BaseModel):
    id: UUID
    position: int = Field(ge=0)


class ReorderPayload(BaseModel):
    items: list[ReorderItem] = Field(min_length=1)


class TaskCardLabelsUpdate(BaseModel):
    label_ids: list[UUID]


class TaskCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class TaskCommentResponse(BaseModel):
    id: UUID
    author_id: UUID
    author_name: str | None = None
    body: str
    created_at: datetime


class TaskChecklistItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class TaskChecklistItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    done: bool | None = None
    position: int | None = Field(default=None, ge=0)


class TaskChecklistItemResponse(BaseModel):
    id: UUID
    title: str
    done: bool
    position: int


class TaskChecklistCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class TaskChecklistUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    position: int | None = Field(default=None, ge=0)


class TaskChecklistResponse(BaseModel):
    id: UUID
    title: str
    position: int
    items: list[TaskChecklistItemResponse]


class TaskCardSummary(BaseModel):
    id: UUID
    list_id: UUID
    title: str
    description: str | None = None
    position: int
    due_on: date | None = None
    priority: Priority
    archived_at: datetime | None = None
    label_ids: list[UUID] = []
    checklist_total: int = 0
    checklist_done: int = 0
    comment_count: int = 0


class TaskCardDetail(TaskCardSummary):
    labels: list[TaskLabelResponse] = []
    comments: list[TaskCommentResponse] = []
    checklists: list[TaskChecklistResponse] = []
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    id: UUID
    name: str
    position: int
    archived_at: datetime | None = None
    cards: list[TaskCardSummary] = []


class TaskBoardDetail(TaskBoardSummary):
    lists: list[TaskListResponse] = []
    labels: list[TaskLabelResponse] = []
