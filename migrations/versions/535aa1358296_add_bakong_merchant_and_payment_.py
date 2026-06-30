"""Add Bakong merchant and payment transaction models

Revision ID: 535aa1358296
Revises:
Create Date: 2026-03-26 19:42:45.386506

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '535aa1358296'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create bakong_merchants table
    op.create_table('bakong_merchants',
    sa.Column('merchant_id', sa.Integer(), nullable=False),
    sa.Column('merchant_name', sa.String(length=100), nullable=False),
    sa.Column('bank_account', sa.String(length=50), nullable=False),
    sa.Column('merchant_city', sa.String(length=50), nullable=False),
    sa.Column('terminal_label', sa.String(length=50), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('merchant_id')
    )

    # Create payment_transactions table
    op.create_table('payment_transactions',
    sa.Column('transaction_id', sa.Integer(), nullable=False),
    sa.Column('qr_string', sa.Text(), nullable=False),
    sa.Column('md5_hash', sa.String(length=32), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('paid_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
    sa.PrimaryKeyConstraint('transaction_id'),
    sa.UniqueConstraint('md5_hash')
    )


def downgrade():
    op.drop_table('payment_transactions')
    op.drop_table('bakong_merchants')
