"""Add users.is_active for customer account suspension

Revision ID: a1c4e7b90d21
Revises: 535aa1358296
Create Date: 2026-08-29

Adds the flag that lets an admin suspend a customer without deleting them.
Existing rows are backfilled to active so nobody is locked out by the upgrade.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c4e7b90d21'
down_revision = '535aa1358296'
branch_labels = None
depends_on = None


def upgrade():
    # Added nullable first so the ALTER succeeds on a table that already has
    # rows; backfilled, then tightened to NOT NULL.
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('is_active', sa.Boolean(), nullable=True))

    op.execute('UPDATE users SET is_active = TRUE WHERE is_active IS NULL')

    with op.batch_alter_table('users') as batch:
        batch.alter_column('is_active', existing_type=sa.Boolean(),
                           nullable=False, server_default=sa.true())


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('is_active')
