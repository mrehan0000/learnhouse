"""Add courseaccessrequest table

Revision ID: b2c3d4e5f6a7
Revises: a9b0c1d2e3f4
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa  # noqa: F401
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'courseaccessrequest',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='PENDING'),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('decided_by_id', sa.Integer(), nullable=True),
        sa.Column('creation_date', sa.String(), nullable=False),
        sa.Column('update_date', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['course.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['decided_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('course_id', 'user_id', name='uq_access_request_course_user'),
    )
    op.create_index(
        op.f('ix_courseaccessrequest_course_id'), 'courseaccessrequest', ['course_id']
    )
    op.create_index(
        op.f('ix_courseaccessrequest_user_id'), 'courseaccessrequest', ['user_id']
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_courseaccessrequest_user_id'), table_name='courseaccessrequest')
    op.drop_index(op.f('ix_courseaccessrequest_course_id'), table_name='courseaccessrequest')
    op.drop_table('courseaccessrequest')
