"""Quadros pessoais de tarefas (kanban)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0010_task_boards"
down_revision = "0009_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_boards",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_task_boards_owner_user", "task_boards", ["owner_id", "user_id"])

    op.create_table(
        "task_lists",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "board_id",
            UUID(),
            sa.ForeignKey("task_boards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_task_lists_board_position", "task_lists", ["board_id", "position"])

    op.create_table(
        "task_cards",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "list_id",
            UUID(),
            sa.ForeignKey("task_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("due_on", sa.Date()),
        sa.Column("priority", sa.Text(), nullable=False, server_default="normal"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high')", name="ck_task_cards_priority"
        ),
    )
    op.create_index("ix_task_cards_list_position", "task_cards", ["list_id", "position"])

    op.create_table(
        "task_labels",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "board_id",
            UUID(),
            sa.ForeignKey("task_boards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False, server_default="#64748b"),
        sa.UniqueConstraint("board_id", "name"),
    )

    op.create_table(
        "task_card_labels",
        sa.Column(
            "card_id",
            UUID(),
            sa.ForeignKey("task_cards.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "label_id",
            UUID(),
            sa.ForeignKey("task_labels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.UniqueConstraint("card_id", "label_id"),
    )

    op.create_table(
        "task_comments",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "card_id",
            UUID(),
            sa.ForeignKey("task_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_id", UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_task_comments_card_id", "task_comments", ["card_id"])

    op.create_table(
        "task_checklists",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "card_id",
            UUID(),
            sa.ForeignKey("task_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_task_checklists_card_position", "task_checklists", ["card_id", "position"]
    )

    op.create_table(
        "task_checklist_items",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "checklist_id",
            UUID(),
            sa.ForeignKey("task_checklists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_task_checklist_items_checklist_position",
        "task_checklist_items",
        ["checklist_id", "position"],
    )


def downgrade() -> None:
    op.drop_table("task_checklist_items")
    op.drop_table("task_checklists")
    op.drop_table("task_comments")
    op.drop_table("task_card_labels")
    op.drop_table("task_labels")
    op.drop_table("task_cards")
    op.drop_table("task_lists")
    op.drop_table("task_boards")
