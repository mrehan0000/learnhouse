"""Add enforce_sequential_progression field to course

Revision ID: a9b0c1d2e3f4
Revises: b1c2d3e4f5a6
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa  # noqa: F401
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-course opt-in toggle: when true, an activity is locked until every
    # earlier activity in the course (by chapter order, then activity order)
    # has a completed TrailStep for the current user. Defaults to False so
    # existing courses are unaffected.
    op.add_column(
        'course',
        sa.Column(
            'enforce_sequential_progression',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('course', 'enforce_sequential_progression')
