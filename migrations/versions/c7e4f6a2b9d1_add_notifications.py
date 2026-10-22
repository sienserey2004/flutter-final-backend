"""Add in-app customer notifications."""
from alembic import op
import sqlalchemy as sa

revision = 'c7e4f6a2b9d1'
down_revision = 'a1c4e7b90d21'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notifications',
        sa.Column('notification_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('notification_id'),
    )


def downgrade():
    op.drop_table('notifications')
