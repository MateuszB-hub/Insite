"""profile certifications

Revision ID: 3c7a9e2f41b8
Revises: a87f0fdf6df7
Create Date: 2026-09-26 18:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c7a9e2f41b8'
down_revision: Union[str, Sequence[str], None] = 'a87f0fdf6df7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('applicant_profiles', sa.Column('certifications', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('applicant_profiles', 'certifications')
