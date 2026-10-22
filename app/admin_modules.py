"""Admin-panel modules a Super Admin can switch on or off for every Admin.

A module with no row in `admin_modules` counts as enabled, so a module added
here shows up for admins straight away; sync_admin_modules() then creates its
row so it appears on the Super Admin's Modules page.
"""
from flask import g

# (key, label, icon, sidebar section) — also the order on the Modules page.
MODULES = [
    ('dashboard',            'Dashboard',              'grid-1x2',            'OVERVIEW'),
    ('brands',               'Brands',                 'award',               'CATALOG'),
    ('categories',           'Categories',             'folder',              'CATALOG'),
    ('products',             'Products',               'box-seam',            'CATALOG'),
    ('bundles',              'Routine Kits',           'gift',                'CATALOG'),
    ('ingredients',          'Ingredients',            'droplet',             'SKINCARE DATA'),
    ('skin_types',           'Skin Types',             'person-bounding-box', 'SKINCARE DATA'),
    ('concerns',             'Skin Concerns',          'bullseye',            'SKINCARE DATA'),
    ('inventory',            'Stock & Expiry',         'list-check',          'INVENTORY'),
    ('stock_alerts',         'Stock Alerts (Mailbox)', 'bell',                'INVENTORY'),
    ('orders',               'Orders',                 'receipt',             'SALES'),
    ('returns',              'Returns',                'arrow-return-left',   'SALES'),
    ('subscriptions',        'Subscriptions',          'arrow-repeat',        'SALES'),
    ('shipping_methods',     'Shipping Methods',       'truck',               'SALES'),
    ('coupons',              'Coupons',                'ticket-perforated',   'SALES'),
    ('promotions',           'Promotions',             'megaphone',           'SALES'),
    ('bakong_merchants',     'Bakong Merchants',       'shop',                'PAYMENTS'),
    ('payment_transactions', 'Transactions',           'credit-card',         'PAYMENTS'),
    ('users',                'Customers',              'people',              'USERS'),
]
MODULE_KEYS = [m[0] for m in MODULES]
MODULE_LABELS = {m[0]: m[1] for m in MODULES}

# Modules that can never be switched off — admins need somewhere to land.
ALWAYS_ON = {'dashboard'}

# Admin endpoint (view function name) → module. An admin endpoint missing from
# here is Super Admin only, so a new route is locked until it's mapped.
ENDPOINT_MODULES = {
    'dashboard': 'dashboard',

    'users': 'users', 'user_detail': 'users', 'new_user': 'users',
    'edit_user': 'users', 'toggle_user_active': 'users', 'delete_user': 'users',

    'brands': 'brands', 'new_brand': 'brands', 'edit_brand': 'brands',
    'delete_brand': 'brands',

    'categories': 'categories', 'new_category': 'categories',
    'edit_category': 'categories', 'delete_category': 'categories',

    'ingredients': 'ingredients', 'new_ingredient': 'ingredients',
    'edit_ingredient': 'ingredients', 'delete_ingredient': 'ingredients',

    'products': 'products', 'new_product': 'products', 'edit_product': 'products',
    'delete_product': 'products', 'product_ingredients': 'products',
    'delete_product_ingredient': 'products', 'product_images': 'products',
    'set_primary_image': 'products', 'delete_product_image': 'products',
    'variants': 'products', 'new_variant': 'products', 'edit_variant': 'products',
    'delete_variant': 'products',

    'bundles': 'bundles', 'new_bundle': 'bundles', 'edit_bundle': 'bundles',
    'add_bundle_item': 'bundles', 'delete_bundle_item': 'bundles',
    'delete_bundle': 'bundles',

    'shipping_methods': 'shipping_methods', 'new_shipping_method': 'shipping_methods',
    'edit_shipping_method': 'shipping_methods',
    'delete_shipping_method': 'shipping_methods',

    'orders': 'orders', 'order_detail': 'orders', 'update_order_status': 'orders',
    'update_tracking': 'orders',

    'returns': 'returns', 'return_detail': 'returns',

    'stock_alerts': 'stock_alerts', 'notify_stock_alerts': 'stock_alerts',

    'subscriptions': 'subscriptions',

    'coupons': 'coupons', 'new_coupon': 'coupons', 'delete_coupon': 'coupons',

    'promotions': 'promotions', 'new_promotion': 'promotions',
    'delete_promotion': 'promotions',

    'inventory': 'inventory',

    'bakong_merchants': 'bakong_merchants', 'new_bakong_merchant': 'bakong_merchants',
    'edit_bakong_merchant': 'bakong_merchants',
    'delete_bakong_merchant': 'bakong_merchants',

    'payment_transactions': 'payment_transactions',
    'check_bulk_payments': 'payment_transactions',
    'download_qr': 'payment_transactions',
}

# /taxonomy/<kind> serves two modules; the URL's kind decides which.
TAXONOMY_ENDPOINTS = {'taxonomy', 'edit_taxonomy', 'delete_taxonomy'}
TAXONOMY_MODULES = {'skin-types': 'skin_types', 'concerns': 'concerns'}


def module_for_endpoint(endpoint, view_args=None):
    """Module key for an admin endpoint ('admin.orders' or 'api_admin.orders'),
    or None when the endpoint isn't mapped."""
    name = (endpoint or '').rsplit('.', 1)[-1]
    if name in TAXONOMY_ENDPOINTS:
        return TAXONOMY_MODULES.get((view_args or {}).get('kind'))
    return ENDPOINT_MODULES.get(name)


def disabled_module_keys():
    """Modules switched off for admins. Cached for the rest of the request."""
    if 'disabled_admin_modules' not in g:
        from app.models import AdminModule
        rows = AdminModule.query.filter_by(is_enabled=False).all()
        g.disabled_admin_modules = {r.module_key for r in rows} - ALWAYS_ON
    return g.disabled_admin_modules


def module_enabled(key, user=None):
    """Whether `user` (default: nobody special) can use module `key`."""
    if user is not None and user.is_super_admin():
        return True
    return key in MODULE_LABELS and key not in disabled_module_keys()


def enabled_module_keys(user=None):
    """Module keys `user` can use, in menu order."""
    if user is not None and user.is_super_admin():
        return list(MODULE_KEYS)
    disabled = disabled_module_keys()
    return [k for k in MODULE_KEYS if k not in disabled]


def sync_admin_modules():
    """Create a row for every module in MODULES that doesn't have one yet, and
    keep labels and order in step with MODULES. Existing switches are kept."""
    from app.models import db, AdminModule
    existing = {m.module_key: m for m in AdminModule.query.all()}
    for order, (key, label, _icon, _section) in enumerate(MODULES):
        row = existing.get(key)
        if row is None:
            db.session.add(AdminModule(module_key=key, label=label,
                                       is_enabled=True, sort_order=order))
        elif row.label != label or row.sort_order != order:
            row.label, row.sort_order = label, order
    db.session.commit()
