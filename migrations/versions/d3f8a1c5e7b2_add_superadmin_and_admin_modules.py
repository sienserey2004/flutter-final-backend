"""Add the SuperAdmin role and the admin_modules on/off switches."""
from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision = 'd3f8a1c5e7b2'
down_revision = 'c7e4f6a2b9d1'
branch_labels = None
depends_on = None

# Snapshot of app/admin_modules.py MODULES at the time of this migration.
MODULES = [
    ('dashboard', 'Dashboard'), ('brands', 'Brands'), ('categories', 'Categories'),
    ('products', 'Products'), ('bundles', 'Routine Kits'),
    ('ingredients', 'Ingredients'), ('skin_types', 'Skin Types'),
    ('concerns', 'Skin Concerns'), ('inventory', 'Stock & Expiry'),
    ('stock_alerts', 'Stock Alerts (Mailbox)'), ('orders', 'Orders'),
    ('returns', 'Returns'), ('subscriptions', 'Subscriptions'),
    ('shipping_methods', 'Shipping Methods'), ('coupons', 'Coupons'),
    ('promotions', 'Promotions'), ('bakong_merchants', 'Bakong Merchants'),
    ('payment_transactions', 'Transactions'), ('users', 'Customers'),
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # The app's db.create_all() at startup may already have made the table.
    if 'admin_modules' not in inspector.get_table_names():
        op.create_table(
            'admin_modules',
            sa.Column('module_key', sa.String(length=50), nullable=False),
            sa.Column('label', sa.String(length=100), nullable=False),
            sa.Column('is_enabled', sa.Boolean(), nullable=False),
            sa.Column('sort_order', sa.Integer(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('updated_by', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['updated_by'], ['users.user_id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('module_key'),
        )

    modules = sa.table('admin_modules',
                       sa.column('module_key', sa.String), sa.column('label', sa.String),
                       sa.column('is_enabled', sa.Boolean), sa.column('sort_order', sa.Integer),
                       sa.column('updated_at', sa.DateTime))
    existing = {r[0] for r in bind.execute(sa.text('SELECT module_key FROM admin_modules'))}
    now = datetime.utcnow()
    rows = [dict(module_key=key, label=label, is_enabled=True, sort_order=i, updated_at=now)
            for i, (key, label) in enumerate(MODULES) if key not in existing]
    if rows:
        op.bulk_insert(modules, rows)

    has_role = bind.execute(sa.text("SELECT 1 FROM roles WHERE role_name = 'SuperAdmin'")).first()
    if not has_role:
        bind.execute(sa.text("INSERT INTO roles (role_name) VALUES ('SuperAdmin')"))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "DELETE FROM user_roles WHERE role_id IN "
        "(SELECT role_id FROM roles WHERE role_name = 'SuperAdmin')"))
    bind.execute(sa.text("DELETE FROM roles WHERE role_name = 'SuperAdmin'"))
    op.drop_table('admin_modules')
