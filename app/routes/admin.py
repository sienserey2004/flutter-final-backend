from flask import (Blueprint, render_template, redirect, url_for, flash, request,
                   abort, send_file, current_app)
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import func
from app.models import (db, User, Role, Brand, Category, Product, ProductVariant,
                        ProductImage, ProductIngredient, Ingredient, SkinType,
                        SkinConcern, Bundle, BundleItem, Order, OrderItem, Payment,
                        Shipping, ShippingMethod, Coupon, Promotion, InventoryLog,
                        Review, ReturnRequest, BackInStockAlert, Subscription,
                        BakongMerchant, PaymentTransaction, Address, Cart,
                        CartItem, Wishlist, WishlistItem)
from app.api import wants_json, api_ok, api_error, form_value, form_list
from app.utils import slugify, unique_slug
import hashlib
from bakong_khqr import KHQR
import qrcode
import io
import requests

admin_bp = Blueprint('admin', __name__)

LOW_STOCK_THRESHOLD = 10
EXPIRY_WARNING_DAYS = 180


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return login_required(decorated)


def _checkbox(name, default=False):
    """HTML checkbox or JSON boolean."""
    if request.is_json:
        return bool((request.get_json(silent=True) or {}).get(name, default))
    return name in request.form


def _date(name):
    raw = form_value(name)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


def _role(role_name):
    """Fetch a role, creating it on first use — a fresh database has no rows in
    `roles` until somebody is given one."""
    role = Role.query.filter_by(role_name=role_name).first()
    if not role:
        role = Role(role_name=role_name)
        db.session.add(role)
        db.session.flush()
    return role


def _name_taken(model, name, pk_field=None, pk_value=None):
    """Brands, ingredients, skin types and concerns all have a UNIQUE name.
    Catch the collision here so it's a form error, not a 500 from the driver."""
    query = model.query.filter(model.name == name)
    if pk_field and pk_value:
        query = query.filter(getattr(model, pk_field) != pk_value)
    return query.first() is not None


def _months_back(n):
    """n+1 first-of-month datetimes, oldest first, ending with the current month."""
    months = []
    y, m = datetime.utcnow().year, datetime.utcnow().month
    for _ in range(n + 1):
        months.append(datetime(y, m, 1))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(months))


# Small live counts for the admin-panel header's notification/mailbox dropdowns —
# these render on every admin page, not just the dashboard.
@admin_bp.context_processor
def inject_admin_chrome():
    expiry_cutoff = (datetime.utcnow() + timedelta(days=EXPIRY_WARNING_DAYS)).date()
    return {
        'admin_low_stock_count': ProductVariant.query
            .filter(ProductVariant.stock <= LOW_STOCK_THRESHOLD).count(),
        'admin_expiring_count': ProductVariant.query
            .filter(ProductVariant.expiry_date.isnot(None),
                    ProductVariant.expiry_date <= expiry_cutoff,
                    ProductVariant.stock > 0).count(),
        'admin_open_returns_count': ReturnRequest.query
            .filter(ReturnRequest.status.in_(['Requested', 'Approved'])).count(),
        'admin_pending_alerts_count': BackInStockAlert.query
            .filter_by(notified_at=None).count(),
        'admin_pending_alerts_preview': BackInStockAlert.query
            .filter_by(notified_at=None)
            .order_by(BackInStockAlert.created_at.desc()).limit(5).all(),
    }


# ── Dashboard ──────────────────────────────────────────────────────────────────
@admin_bp.route('/')
@admin_required
def dashboard():
    low_stock = (ProductVariant.query
                 .filter(ProductVariant.stock <= LOW_STOCK_THRESHOLD)
                 .order_by(ProductVariant.stock.asc()).limit(10).all())
    expiry_cutoff = (datetime.utcnow() + timedelta(days=EXPIRY_WARNING_DAYS)).date()
    expiring = (ProductVariant.query
                .filter(ProductVariant.expiry_date.isnot(None),
                        ProductVariant.expiry_date <= expiry_cutoff,
                        ProductVariant.stock > 0)
                .order_by(ProductVariant.expiry_date.asc()).limit(10).all())

    stats = {
        'users':    User.query.count(),
        'products': Product.query.count(),
        'variants': ProductVariant.query.count(),
        'brands':   Brand.query.count(),
        'orders':   Order.query.count(),
        'revenue':  db.session.query(db.func.sum(Order.total_amount))
                              .filter(Order.status == 'Delivered').scalar() or 0,
        'open_returns': ReturnRequest.query.filter(
                            ReturnRequest.status.in_(['Requested', 'Approved'])).count(),
        'low_stock':    len(low_stock),
        'expiring':     len(expiring),
        'subscriptions': Subscription.query.filter_by(status='Active').count(),
        'pending_alerts': BackInStockAlert.query.filter_by(notified_at=None).count(),
    }
    recent_orders  = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    order_statuses = {s: Order.query.filter_by(status=s).count()
                      for s in Order.STATUS_CHOICES}

    # Which concerns is the catalog actually serving?
    concern_coverage = (db.session.query(SkinConcern.name, func.count(Product.product_id))
                        .outerjoin(SkinConcern.products)
                        .group_by(SkinConcern.name)
                        .order_by(func.count(Product.product_id).desc()).all())

    # Orders + revenue for the last 6 months, for the dashboard's trend chart.
    # Bucketed in Python rather than SQL (e.g. date_trunc) so this works the same
    # on SQLite (local dev) and Postgres (production).
    month_buckets = _months_back(5)
    monthly_map = {}
    for created_at, total_amount in (Order.query
                                      .with_entities(Order.created_at, Order.total_amount)
                                      .filter(Order.created_at >= month_buckets[0])):
        key = created_at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        count, revenue = monthly_map.get(key, (0, 0.0))
        monthly_map[key] = (count + 1, revenue + float(total_amount))
    monthly_labels = [m.strftime('%b %Y') for m in month_buckets]
    monthly_order_counts = [monthly_map.get(m, (0, 0.0))[0] for m in month_buckets]
    monthly_revenue = [round(monthly_map.get(m, (0, 0.0))[1], 2) for m in month_buckets]

    if wants_json():
        return api_ok({
            'stats': {**stats, 'revenue': float(stats['revenue'])},
            'recent_orders': [o.to_dict(include_items=False) for o in recent_orders],
            'order_statuses': order_statuses,
            'low_stock': [v.to_dict() for v in low_stock],
            'expiring': [v.to_dict() for v in expiring],
            'concern_coverage': [{'concern': n, 'products': c} for n, c in concern_coverage],
            'monthly_labels': monthly_labels,
            'monthly_order_counts': monthly_order_counts,
            'monthly_revenue': monthly_revenue,
        })
    return render_template('admin/dashboard.html',
                           stats=stats,
                           recent_orders=recent_orders,
                           order_statuses=order_statuses,
                           low_stock=low_stock,
                           expiring=expiring,
                           concern_coverage=concern_coverage,
                           monthly_labels=monthly_labels,
                           monthly_order_counts=monthly_order_counts,
                           monthly_revenue=monthly_revenue)


# ── Customers / Users ──────────────────────────────────────────────────────────
def _admin_count():
    """How many active admins are left — used to refuse the change that would
    lock everyone out of the admin panel."""
    return (User.query.filter(User.is_active.is_(True))
            .filter(User.roles.any(Role.role_name == 'Admin')).count())


@admin_bp.route('/users')
@admin_required
def users():
    """Customer list with search and role/status filters."""
    q      = (request.args.get('q') or '').strip()
    role   = (request.args.get('role') or '').strip()     # Admin | Customer
    status = (request.args.get('status') or '').strip()   # active | inactive

    query = User.query
    if q:
        term = f'%{q}%'
        query = query.filter(db.or_(User.name.ilike(term),
                                    User.email.ilike(term),
                                    User.phone.ilike(term)))
    if role:
        query = query.filter(User.roles.any(Role.role_name == role))
    if status == 'active':
        query = query.filter(User.is_active.is_(True))
    elif status == 'inactive':
        query = query.filter(User.is_active.is_(False))

    users = query.order_by(User.created_at.desc()).all()

    stats = {
        'total':    User.query.count(),
        'active':   User.query.filter(User.is_active.is_(True)).count(),
        'inactive': User.query.filter(User.is_active.is_(False)).count(),
        'admins':   User.query.filter(User.roles.any(Role.role_name == 'Admin')).count(),
        'new_30d':  User.query.filter(
                        User.created_at >= datetime.utcnow() - timedelta(days=30)).count(),
    }

    if wants_json():
        return api_ok([u.to_dict() for u in users], count=len(users), stats=stats)
    return render_template('admin/users.html', users=users, stats=stats,
                           q=q, role=role, status=status)


@admin_bp.route('/users/<int:user_id>')
@admin_required
def user_detail(user_id):
    """One customer: profile, lifetime value, orders, reviews, addresses."""
    user = User.query.get_or_404(user_id)

    orders    = user.orders.order_by(Order.order_date.desc()).all()
    reviews   = user.reviews.order_by(Review.created_at.desc()).all()
    addresses = user.addresses.order_by(Address.is_default.desc()).all()
    stats     = user.order_stats()

    status_counts = {}
    for o in orders:
        status_counts[o.status] = status_counts.get(o.status, 0) + 1

    if wants_json():
        return api_ok({
            'user': user.to_dict(include_stats=True),
            'orders': [o.to_dict(include_items=False) for o in orders],
            'reviews': [r.to_dict() for r in reviews],
            'addresses': [a.to_dict() for a in addresses],
            'wishlist': user.wishlist.to_dict() if user.wishlist else None,
            'status_counts': status_counts,
        })
    return render_template('admin/user_detail.html', user=user, orders=orders,
                           reviews=reviews, addresses=addresses, stats=stats,
                           status_counts=status_counts)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@admin_required
def new_user():
    """Create a customer (or a fellow admin) from the panel."""
    if request.method == 'POST':
        name     = (form_value('name', '') or '').strip()
        email    = (form_value('email', '') or '').strip().lower()
        phone    = (form_value('phone', '') or '').strip()
        password = form_value('password', '') or ''
        is_admin = _checkbox('is_admin')

        errors = []
        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
        elif User.query.filter_by(email=email).first():
            errors.append('That email is already registered.')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')

        if errors:
            if wants_json():
                return api_error('Validation failed', 422, errors=errors)
            for e in errors:
                flash(e, 'danger')
            return render_template('admin/user_form.html', user=None, name=name,
                                   email=email, phone=phone, is_admin=is_admin)

        user = User(name=name, email=email, phone=phone, is_active=True)
        user.set_password(password)
        user.roles.append(_role('Customer'))
        if is_admin:
            user.roles.append(_role('Admin'))
        db.session.add(user)
        db.session.flush()
        db.session.add(Cart(user_id=user.user_id))
        db.session.commit()

        if wants_json():
            return api_ok(user.to_dict(), status=201)
        flash(f'Customer {user.name} created.', 'success')
        return redirect(url_for('admin.user_detail', user_id=user.user_id))

    if wants_json():
        return api_error('GET not supported; POST name/email/password.', 405)
    return render_template('admin/user_form.html', user=None)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    """Edit a customer's contact details, or set a new password for them."""
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        name     = (form_value('name', user.name) or '').strip()
        email    = (form_value('email', user.email) or '').strip().lower()
        phone    = (form_value('phone', user.phone or '') or '').strip()
        password = form_value('password', '') or ''

        errors = []
        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
        elif User.query.filter(User.email == email,
                               User.user_id != user.user_id).first():
            errors.append('That email belongs to another account.')
        if password and len(password) < 6:
            errors.append('Password must be at least 6 characters.')

        if errors:
            if wants_json():
                return api_error('Validation failed', 422, errors=errors)
            for e in errors:
                flash(e, 'danger')
            return render_template('admin/user_form.html', user=user)

        user.name, user.email, user.phone = name, email, phone
        if password:
            user.set_password(password)
        db.session.commit()

        if wants_json():
            return api_ok(user.to_dict())
        flash(f'{user.name} updated.', 'success')
        return redirect(url_for('admin.user_detail', user_id=user.user_id))

    if wants_json():
        return api_ok(user.to_dict(include_stats=True))
    return render_template('admin/user_form.html', user=user)


@admin_bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.user_id == current_user.user_id:
        if wants_json():
            return api_error('Cannot modify your own role.', 422)
        flash("Cannot modify your own role.", 'warning')
        return redirect(request.referrer or url_for('admin.users'))

    admin_role = _role('Admin')
    if user.has_role('Admin'):
        if _admin_count() <= 1:
            message = 'This is the last active admin — promote someone else first.'
            if wants_json():
                return api_error(message, 422)
            flash(message, 'warning')
            return redirect(request.referrer or url_for('admin.users'))
        user.roles.remove(admin_role)
        message, category = f'{user.name} is no longer Admin.', 'info'
    else:
        user.roles.append(admin_role)
        message, category = f'{user.name} is now Admin.', 'success'
    db.session.commit()

    if wants_json():
        return api_ok(user.to_dict(), message=message)
    flash(message, category)
    return redirect(request.referrer or url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_user_active(user_id):
    """Suspend or restore an account. A suspended user can't sign in, and any
    API token they still hold stops working on their next request."""
    user = User.query.get_or_404(user_id)

    if user.user_id == current_user.user_id:
        reason = 'Cannot deactivate your own account.'
    elif user.is_active and user.has_role('Admin') and _admin_count() <= 1:
        reason = 'This is the last active admin — promote someone else first.'
    else:
        reason = None

    if reason:
        if wants_json():
            return api_error(reason, 422)
        flash(reason, 'warning')
        return redirect(request.referrer or url_for('admin.users'))

    user.is_active = not user.is_active
    db.session.commit()

    message = (f'{user.name} reactivated.' if user.is_active
               else f'{user.name} deactivated — they can no longer sign in.')
    if wants_json():
        return api_ok(user.to_dict(), message=message)
    flash(message, 'success' if user.is_active else 'info')
    return redirect(request.referrer or url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    """Hard-delete an account. Refused once the customer has placed an order —
    order history is a financial record and has to survive; deactivate instead."""
    user = User.query.get_or_404(user_id)
    order_count = user.orders.count()

    if user.user_id == current_user.user_id:
        reason = 'Cannot delete your own account.'
    elif order_count:
        reason = (f'{user.name} has {order_count} order(s). '
                  'Deactivate the account instead so order history is kept.')
    elif user.has_role('Admin') and _admin_count() <= 1:
        reason = 'This is the last active admin — promote someone else first.'
    else:
        reason = None

    if reason:
        if wants_json():
            return api_error(reason, 422)
        flash(reason, 'warning')
        return redirect(request.referrer or url_for('admin.users'))

    name = user.name
    # Rows pointing at the user without a cascade have to go first, or the
    # foreign key rejects the delete.
    Review.query.filter_by(user_id=user.user_id).delete(synchronize_session=False)
    BackInStockAlert.query.filter_by(user_id=user.user_id).delete(synchronize_session=False)
    Subscription.query.filter_by(user_id=user.user_id).delete(synchronize_session=False)
    ReturnRequest.query.filter_by(user_id=user.user_id).delete(synchronize_session=False)
    if user.cart:
        CartItem.query.filter_by(cart_id=user.cart.cart_id).delete(synchronize_session=False)
        db.session.delete(user.cart)
    if user.wishlist:
        WishlistItem.query.filter_by(wishlist_id=user.wishlist.wishlist_id) \
                          .delete(synchronize_session=False)
        db.session.delete(user.wishlist)
    user.roles = []
    db.session.delete(user)
    db.session.commit()

    if wants_json():
        return api_ok(message=f'{name} deleted.')
    flash(f'{name} deleted.', 'success')
    return redirect(url_for('admin.users'))


# ── Brands ─────────────────────────────────────────────────────────────────────
@admin_bp.route('/brands')
@admin_required
def brands():
    items = Brand.query.order_by(Brand.name).all()
    if wants_json():
        return api_ok([b.to_dict() for b in items])
    return render_template('admin/brands.html', brands=items)


@admin_bp.route('/brands/new', methods=['GET', 'POST'])
@admin_required
def new_brand():
    if request.method == 'POST':
        name = (form_value('name', '') or '').strip()
        if not name:
            if wants_json():
                return api_error('Name required.', 422)
            flash('Name required.', 'danger')
            return render_template('admin/brand_form.html', brand=None)
        if _name_taken(Brand, name):
            if wants_json():
                return api_error(f'A brand called "{name}" already exists.', 409)
            flash(f'A brand called "{name}" already exists.', 'danger')
            return render_template('admin/brand_form.html', brand=None)
        brand = Brand(
            name=name,
            slug=unique_slug(Brand, name),
            country=(form_value('country', '') or '').strip() or None,
            logo=(form_value('logo', '') or '').strip() or None,
            description=(form_value('description', '') or '').strip() or None,
            is_active=_checkbox('is_active'),
        )
        db.session.add(brand)
        db.session.commit()
        flash('Brand created.', 'success')
        if wants_json():
            return api_ok(brand.to_dict(), status=201)
        return redirect(url_for('admin.brands'))
    if wants_json():
        return api_error('POST name/country/logo/description to create a brand.', 405)
    return render_template('admin/brand_form.html', brand=None)


@admin_bp.route('/brands/<int:brand_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    if request.method == 'POST':
        new_name = (form_value('name', brand.name) or '').strip()
        if new_name != brand.name:
            if _name_taken(Brand, new_name, 'brand_id', brand.brand_id):
                if wants_json():
                    return api_error(f'A brand called "{new_name}" already exists.', 409)
                flash(f'A brand called "{new_name}" already exists.', 'danger')
                return render_template('admin/brand_form.html', brand=brand)
            brand.slug = unique_slug(Brand, new_name, pk_field='brand_id', pk_value=brand.brand_id)
        brand.name = new_name
        brand.country = (form_value('country', '') or '').strip() or None
        brand.logo = (form_value('logo', '') or '').strip() or None
        brand.description = (form_value('description', '') or '').strip() or None
        brand.is_active = _checkbox('is_active')
        db.session.commit()
        flash('Brand updated.', 'success')
        if wants_json():
            return api_ok(brand.to_dict())
        return redirect(url_for('admin.brands'))
    if wants_json():
        return api_ok(brand.to_dict())
    return render_template('admin/brand_form.html', brand=brand)


@admin_bp.route('/brands/<int:brand_id>/delete', methods=['POST'])
@admin_required
def delete_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    if brand.products.count():
        msg = f'{brand.name} still has {brand.products.count()} product(s). Reassign them first.'
        if wants_json():
            return api_error(msg, 409)
        flash(msg, 'warning')
        return redirect(url_for('admin.brands'))
    db.session.delete(brand)
    db.session.commit()
    flash('Brand deleted.', 'info')
    if wants_json():
        return api_ok(message='Brand deleted.')
    return redirect(url_for('admin.brands'))


# ── Categories ─────────────────────────────────────────────────────────────────
@admin_bp.route('/categories')
@admin_required
def categories():
    cats = Category.query.order_by(Category.sort_order, Category.name).all()
    if wants_json():
        return api_ok([c.to_dict() for c in cats])
    return render_template('admin/categories.html', categories=cats)


@admin_bp.route('/categories/new', methods=['GET', 'POST'])
@admin_required
def new_category():
    parents = Category.query.order_by(Category.name).all()
    if request.method == 'POST':
        name = (form_value('name', '') or '').strip()
        if not name:
            if wants_json():
                return api_error('Name required.', 422)
            flash('Name required.', 'danger')
            return render_template('admin/category_form.html', category=None, parents=parents)
        cat = Category(
            name=name,
            slug=unique_slug(Category, name),
            parent_id=form_value('parent_id', cast=int) or None,
            description=(form_value('description', '') or '').strip() or None,
            image=(form_value('image', '') or '').strip() or None,
            sort_order=form_value('sort_order', 0, cast=int) or 0,
        )
        db.session.add(cat)
        db.session.commit()
        flash('Category created.', 'success')
        if wants_json():
            return api_ok(cat.to_dict(), status=201)
        return redirect(url_for('admin.categories'))
    if wants_json():
        return api_error('POST name/parent_id/description to create a category.', 405)
    return render_template('admin/category_form.html', category=None, parents=parents)


@admin_bp.route('/categories/<int:cat_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    parents = Category.query.filter(Category.category_id != cat_id)\
                            .order_by(Category.name).all()
    if request.method == 'POST':
        new_name = (form_value('name', cat.name) or '').strip()
        if new_name != cat.name:
            cat.slug = unique_slug(Category, new_name, pk_field='category_id', pk_value=cat_id)
        cat.name = new_name
        parent_id = form_value('parent_id', cast=int) or None
        # Guard against a category becoming its own ancestor.
        if parent_id and parent_id in cat.descendant_ids():
            msg = 'A category cannot be nested inside itself or its own child.'
            if wants_json():
                return api_error(msg, 422)
            flash(msg, 'danger')
            return render_template('admin/category_form.html', category=cat, parents=parents)
        cat.parent_id   = parent_id
        cat.description = (form_value('description', '') or '').strip() or None
        cat.image       = (form_value('image', '') or '').strip() or None
        cat.sort_order  = form_value('sort_order', 0, cast=int) or 0
        db.session.commit()
        flash('Category updated.', 'success')
        if wants_json():
            return api_ok(cat.to_dict())
        return redirect(url_for('admin.categories'))
    if wants_json():
        return api_ok(cat.to_dict(include_children=True))
    return render_template('admin/category_form.html', category=cat, parents=parents)


@admin_bp.route('/categories/<int:cat_id>/delete', methods=['POST'])
@admin_required
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    if cat.products.count() or cat.children.count():
        msg = 'Category still has products or sub-categories. Move them first.'
        if wants_json():
            return api_error(msg, 409)
        flash(msg, 'warning')
        return redirect(url_for('admin.categories'))
    db.session.delete(cat)
    db.session.commit()
    flash('Category deleted.', 'info')
    if wants_json():
        return api_ok(message='Category deleted.')
    return redirect(url_for('admin.categories'))


# ── Skin types & concerns (shared taxonomy screens) ────────────────────────────
TAXONOMIES = {
    'skin-types': dict(model=SkinType, pk='skin_type_id', label='Skin Type',
                       plural='Skin Types'),
    'concerns':   dict(model=SkinConcern, pk='concern_id', label='Skin Concern',
                       plural='Skin Concerns'),
}


def _taxonomy(kind):
    meta = TAXONOMIES.get(kind)
    if not meta:
        abort(404)
    return meta


@admin_bp.route('/taxonomy/<kind>', methods=['GET', 'POST'])
@admin_required
def taxonomy(kind):
    meta = _taxonomy(kind)
    model = meta['model']

    if request.method == 'POST':
        name = (form_value('name', '') or '').strip()
        if not name:
            if wants_json():
                return api_error('Name required.', 422)
            flash('Name required.', 'danger')
            return redirect(url_for('admin.taxonomy', kind=kind))
        if _name_taken(model, name):
            if wants_json():
                return api_error(f'"{name}" already exists.', 409)
            flash(f'"{name}" already exists.', 'danger')
            return redirect(url_for('admin.taxonomy', kind=kind))
        item = model(name=name, slug=unique_slug(model, name),
                     icon=(form_value('icon', '') or '').strip() or None,
                     description=(form_value('description', '') or '').strip() or None)
        db.session.add(item)
        db.session.commit()
        flash(f'{meta["label"]} added.', 'success')
        if wants_json():
            return api_ok(item.to_dict(), status=201)
        return redirect(url_for('admin.taxonomy', kind=kind))

    items = model.query.order_by(model.name).all()
    if wants_json():
        return api_ok([i.to_dict() for i in items])
    return render_template('admin/taxonomy.html', kind=kind, meta=meta, items=items)


@admin_bp.route('/taxonomy/<kind>/<int:item_id>/edit', methods=['POST'])
@admin_required
def edit_taxonomy(kind, item_id):
    meta = _taxonomy(kind)
    item = meta['model'].query.get_or_404(item_id)
    new_name = (form_value('name', item.name) or '').strip()
    if new_name != item.name:
        if _name_taken(meta['model'], new_name, meta['pk'], item_id):
            if wants_json():
                return api_error(f'"{new_name}" already exists.', 409)
            flash(f'"{new_name}" already exists.', 'danger')
            return redirect(url_for('admin.taxonomy', kind=kind))
        item.slug = unique_slug(meta['model'], new_name,
                                pk_field=meta['pk'], pk_value=item_id)
    item.name = new_name
    item.icon = (form_value('icon', '') or '').strip() or None
    item.description = (form_value('description', '') or '').strip() or None
    db.session.commit()
    flash(f'{meta["label"]} updated.', 'success')
    if wants_json():
        return api_ok(item.to_dict())
    return redirect(url_for('admin.taxonomy', kind=kind))


@admin_bp.route('/taxonomy/<kind>/<int:item_id>/delete', methods=['POST'])
@admin_required
def delete_taxonomy(kind, item_id):
    meta = _taxonomy(kind)
    item = meta['model'].query.get_or_404(item_id)
    if item.products.count():
        msg = f'{item.name} is still linked to {item.products.count()} product(s).'
        if wants_json():
            return api_error(msg, 409)
        flash(msg, 'warning')
        return redirect(url_for('admin.taxonomy', kind=kind))
    db.session.delete(item)
    db.session.commit()
    flash(f'{meta["label"]} deleted.', 'info')
    if wants_json():
        return api_ok(message='Deleted.')
    return redirect(url_for('admin.taxonomy', kind=kind))


# ── Ingredients ────────────────────────────────────────────────────────────────
@admin_bp.route('/ingredients')
@admin_required
def ingredients():
    items = Ingredient.query.order_by(Ingredient.name).all()
    if wants_json():
        return api_ok([i.to_dict() for i in items])
    return render_template('admin/ingredients.html', ingredients=items)


def _save_ingredient(ing):
    new_name = (form_value('name', ing.name if ing.ingredient_id else '') or '').strip()
    if not new_name:
        return False
    if new_name != ing.name:
        ing.slug = unique_slug(Ingredient, new_name, pk_field='ingredient_id',
                               pk_value=ing.ingredient_id)
    ing.name = new_name
    ing.inci_name    = (form_value('inci_name', '') or '').strip() or None
    ing.benefits     = (form_value('benefits', '') or '').strip() or None
    ing.description  = (form_value('description', '') or '').strip() or None
    ing.caution_note = (form_value('caution_note', '') or '').strip() or None
    ing.is_active_ingredient = _checkbox('is_active_ingredient')
    return True


@admin_bp.route('/ingredients/new', methods=['GET', 'POST'])
@admin_required
def new_ingredient():
    if request.method == 'POST':
        ing = Ingredient(name='', slug='')
        if not _save_ingredient(ing):
            if wants_json():
                return api_error('Name required.', 422)
            flash('Name required.', 'danger')
            return render_template('admin/ingredient_form.html', ingredient=None)
        if _name_taken(Ingredient, ing.name):
            if wants_json():
                return api_error(f'"{ing.name}" is already in the ingredient list.', 409)
            flash(f'"{ing.name}" is already in the ingredient list.', 'danger')
            return render_template('admin/ingredient_form.html', ingredient=None)
        ing.slug = unique_slug(Ingredient, ing.name)
        db.session.add(ing)
        db.session.commit()
        flash('Ingredient created.', 'success')
        if wants_json():
            return api_ok(ing.to_dict(), status=201)
        return redirect(url_for('admin.ingredients'))
    if wants_json():
        return api_error('POST name/inci_name/benefits to create an ingredient.', 405)
    return render_template('admin/ingredient_form.html', ingredient=None)


@admin_bp.route('/ingredients/<int:ingredient_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_ingredient(ingredient_id):
    ing = Ingredient.query.get_or_404(ingredient_id)
    if request.method == 'POST':
        submitted = (form_value('name', ing.name) or '').strip()
        if submitted and _name_taken(Ingredient, submitted, 'ingredient_id', ingredient_id):
            if wants_json():
                return api_error(f'"{submitted}" is already in the ingredient list.', 409)
            flash(f'"{submitted}" is already in the ingredient list.', 'danger')
            return render_template('admin/ingredient_form.html', ingredient=ing)
        if not _save_ingredient(ing):
            if wants_json():
                return api_error('Name required.', 422)
            flash('Name required.', 'danger')
            return render_template('admin/ingredient_form.html', ingredient=ing)
        db.session.commit()
        flash('Ingredient updated.', 'success')
        if wants_json():
            return api_ok(ing.to_dict())
        return redirect(url_for('admin.ingredients'))
    if wants_json():
        return api_ok(ing.to_dict())
    return render_template('admin/ingredient_form.html', ingredient=ing)


@admin_bp.route('/ingredients/<int:ingredient_id>/delete', methods=['POST'])
@admin_required
def delete_ingredient(ingredient_id):
    ing = Ingredient.query.get_or_404(ingredient_id)
    if ing.product_links.count():
        msg = f'{ing.name} is used by {ing.product_links.count()} product(s).'
        if wants_json():
            return api_error(msg, 409)
        flash(msg, 'warning')
        return redirect(url_for('admin.ingredients'))
    db.session.delete(ing)
    db.session.commit()
    flash('Ingredient deleted.', 'info')
    if wants_json():
        return api_ok(message='Ingredient deleted.')
    return redirect(url_for('admin.ingredients'))


# ── Products ───────────────────────────────────────────────────────────────────
@admin_bp.route('/products')
@admin_required
def products():
    query = Product.query
    brand_id = request.args.get('brand', type=int)
    ptype    = request.args.get('type', '').strip()
    if brand_id:
        query = query.filter_by(brand_id=brand_id)
    if ptype:
        query = query.filter_by(product_type=ptype)
    prods = query.order_by(Product.created_at.desc()).all()
    if wants_json():
        return api_ok([p.to_dict(include_variants=False) for p in prods])
    return render_template('admin/products.html', products=prods,
                           brands=Brand.query.order_by(Brand.name).all(),
                           product_types=Product.PRODUCT_TYPES,
                           current_brand=brand_id, current_type=ptype)


def _product_form_context(product=None):
    return dict(
        product=product,
        categories=Category.query.order_by(Category.sort_order, Category.name).all(),
        brands=Brand.query.filter_by(is_active=True).order_by(Brand.name).all(),
        skin_types=SkinType.query.order_by(SkinType.skin_type_id).all(),
        concerns=SkinConcern.query.order_by(SkinConcern.name).all(),
        all_ingredients=Ingredient.query.order_by(Ingredient.name).all(),
        product_types=Product.PRODUCT_TYPES,
        textures=Product.TEXTURES,
        routine_steps=Product.ROUTINE_STEPS,
        selected_skin_types=[s.skin_type_id for s in product.skin_types] if product else [],
        selected_concerns=[c.concern_id for c in product.concerns] if product else [],
    )


def _save_product_fields(product):
    product.category_id  = form_value('category_id', cast=int)
    product.brand_id     = form_value('brand_id', cast=int) or None
    product.description  = (form_value('description', '') or '').strip() or None
    product.base_price   = form_value('base_price', cast=float)
    product.product_type = (form_value('product_type', '') or '').strip() or None
    product.routine_step = form_value('routine_step', cast=int) or None
    product.texture      = (form_value('texture', '') or '').strip() or None
    product.how_to_use   = (form_value('how_to_use', '') or '').strip() or None
    product.ingredients_full = (form_value('ingredients_full', '') or '').strip() or None
    product.spf          = form_value('spf', cast=int) or None
    product.pao_months   = form_value('pao_months', cast=int) or None
    product.volume_label = (form_value('volume_label', '') or '').strip() or None
    product.is_vegan               = _checkbox('is_vegan')
    product.is_cruelty_free        = _checkbox('is_cruelty_free')
    product.is_fragrance_free      = _checkbox('is_fragrance_free')
    product.is_non_comedogenic     = _checkbox('is_non_comedogenic')
    product.is_dermatologist_tested = _checkbox('is_dermatologist_tested')
    product.is_active              = _checkbox('is_active')


def _sync_product_taxonomies(product):
    """Replace the product's skin-type and concern links with what was submitted."""
    chosen_types = set(form_list('skin_type_ids', cast=int))
    current_types = {s.skin_type_id: s for s in product.skin_types}
    for sid in chosen_types - set(current_types):
        st = SkinType.query.get(sid)
        if st:
            product.skin_types.append(st)
    for sid in set(current_types) - chosen_types:
        product.skin_types.remove(current_types[sid])

    chosen_concerns = set(form_list('concern_ids', cast=int))
    current_concerns = {c.concern_id: c for c in product.concerns}
    for cid in chosen_concerns - set(current_concerns):
        cn = SkinConcern.query.get(cid)
        if cn:
            product.concerns.append(cn)
    for cid in set(current_concerns) - chosen_concerns:
        product.concerns.remove(current_concerns[cid])


@admin_bp.route('/products/new', methods=['GET', 'POST'])
@admin_required
def new_product():
    if request.method == 'POST':
        name = (form_value('name', '') or '').strip()
        cat_id = form_value('category_id', cast=int)
        base_price = form_value('base_price', cast=float)
        if not name or not cat_id or base_price is None:
            if wants_json():
                return api_error('Name, category and base price are required.', 422)
            flash('Name, category and base price are required.', 'danger')
            return render_template('admin/product_form.html', **_product_form_context())
        product = Product(name=name, slug=unique_slug(Product, name),
                          category_id=cat_id, base_price=base_price)
        _save_product_fields(product)
        product.name = name
        db.session.add(product)
        db.session.flush()
        _sync_product_taxonomies(product)
        db.session.commit()
        flash('Product created — now add its variants, images and ingredients.', 'success')
        if wants_json():
            return api_ok(product.to_dict(), status=201)
        return redirect(url_for('admin.edit_product', product_id=product.product_id))
    if wants_json():
        return api_error('POST name/category_id/base_price and the skincare fields.', 405)
    return render_template('admin/product_form.html', **_product_form_context())


@admin_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        new_name = (form_value('name', product.name) or '').strip()
        if new_name != product.name:
            product.slug = unique_slug(Product, new_name, pk_field='product_id',
                                       pk_value=product_id)
        product.name = new_name
        _save_product_fields(product)
        _sync_product_taxonomies(product)
        db.session.commit()
        flash('Product updated.', 'success')
        if wants_json():
            return api_ok(product.to_dict())
        return redirect(url_for('admin.products'))
    if wants_json():
        return api_ok(product.to_dict(include_detail=True))
    return render_template('admin/product_form.html', **_product_form_context(product))


@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@admin_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'info')
    if wants_json():
        return api_ok(message='Product deleted.')
    return redirect(url_for('admin.products'))


# ── Product ingredients ────────────────────────────────────────────────────────
@admin_bp.route('/products/<int:product_id>/ingredients', methods=['GET', 'POST'])
@admin_required
def product_ingredients(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        ingredient_id = form_value('ingredient_id', cast=int)
        if not ingredient_id:
            if wants_json():
                return api_error('Pick an ingredient.', 422)
            flash('Pick an ingredient.', 'danger')
            return redirect(url_for('admin.product_ingredients', product_id=product_id))
        existing = product.ingredient_links.filter_by(ingredient_id=ingredient_id).first()
        if existing:
            existing.concentration = (form_value('concentration', '') or '').strip() or None
            existing.is_key = _checkbox('is_key')
            flash('Ingredient updated on this product.', 'success')
            link = existing
        else:
            link = ProductIngredient(
                product_id=product_id, ingredient_id=ingredient_id,
                concentration=(form_value('concentration', '') or '').strip() or None,
                is_key=_checkbox('is_key'))
            db.session.add(link)
            flash('Ingredient linked.', 'success')
        db.session.commit()
        if wants_json():
            return api_ok(link.to_dict(), status=201)
        return redirect(url_for('admin.product_ingredients', product_id=product_id))

    if wants_json():
        return api_ok({
            'product': product.to_dict(include_variants=False, include_detail=True),
            'available': [i.to_dict() for i in Ingredient.query.order_by(Ingredient.name)],
        })
    return render_template('admin/product_ingredients.html', product=product,
                           all_ingredients=Ingredient.query.order_by(Ingredient.name).all())


@admin_bp.route('/products/<int:product_id>/ingredients/<int:link_id>/delete', methods=['POST'])
@admin_required
def delete_product_ingredient(product_id, link_id):
    link = ProductIngredient.query.get_or_404(link_id)
    if link.product_id != product_id:
        abort(404)
    db.session.delete(link)
    db.session.commit()
    flash('Ingredient unlinked.', 'info')
    if wants_json():
        return api_ok(message='Ingredient unlinked.')
    return redirect(url_for('admin.product_ingredients', product_id=product_id))


# ── Product images ─────────────────────────────────────────────────────────────
@admin_bp.route('/products/<int:product_id>/images', methods=['GET', 'POST'])
@admin_required
def product_images(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        url = (form_value('url', '') or '').strip()
        if not url:
            if wants_json():
                return api_error('Image URL required.', 422)
            flash('Image URL required.', 'danger')
            return redirect(url_for('admin.product_images', product_id=product_id))
        is_primary = _checkbox('is_primary')
        if is_primary:
            product.images.update({'is_primary': False})
        image = ProductImage(
            product_id=product_id, url=url,
            alt_text=(form_value('alt_text', '') or '').strip() or None,
            sort_order=form_value('sort_order', product.images.count(), cast=int) or 0,
            is_primary=is_primary or product.images.count() == 0)
        db.session.add(image)
        db.session.commit()
        flash('Image added.', 'success')
        if wants_json():
            return api_ok(image.to_dict(), status=201)
        return redirect(url_for('admin.product_images', product_id=product_id))

    if wants_json():
        return api_ok([i.to_dict() for i in product.images])
    return render_template('admin/product_images.html', product=product)


@admin_bp.route('/products/<int:product_id>/images/<int:image_id>/primary', methods=['POST'])
@admin_required
def set_primary_image(product_id, image_id):
    product = Product.query.get_or_404(product_id)
    image = ProductImage.query.get_or_404(image_id)
    if image.product_id != product_id:
        abort(404)
    product.images.update({'is_primary': False})
    image.is_primary = True
    db.session.commit()
    flash('Primary image set.', 'success')
    if wants_json():
        return api_ok(image.to_dict())
    return redirect(url_for('admin.product_images', product_id=product_id))


@admin_bp.route('/products/<int:product_id>/images/<int:image_id>/delete', methods=['POST'])
@admin_required
def delete_product_image(product_id, image_id):
    image = ProductImage.query.get_or_404(image_id)
    if image.product_id != product_id:
        abort(404)
    db.session.delete(image)
    db.session.commit()
    flash('Image removed.', 'info')
    if wants_json():
        return api_ok(message='Image removed.')
    return redirect(url_for('admin.product_images', product_id=product_id))


# ── Variants ───────────────────────────────────────────────────────────────────
@admin_bp.route('/products/<int:product_id>/variants')
@admin_required
def variants(product_id):
    product = Product.query.get_or_404(product_id)
    if wants_json():
        return api_ok(product.to_dict())
    return render_template('admin/variants.html', product=product)


def _save_variant_fields(variant):
    variant.sku    = (form_value('sku', '') or '').strip() or None
    variant.volume = (form_value('volume', '') or '').strip() or None
    variant.shade  = (form_value('shade', '') or '').strip() or None
    variant.price  = form_value('price', cast=float)
    compare = form_value('compare_at_price', cast=float)
    variant.compare_at_price = compare if compare else None
    variant.weight_grams = form_value('weight_grams', cast=int) or None
    variant.batch_no = (form_value('batch_no', '') or '').strip() or None
    variant.expiry_date = _date('expiry_date')
    variant.image  = (form_value('image', '') or '').strip() or None


@admin_bp.route('/products/<int:product_id>/variants/new', methods=['GET', 'POST'])
@admin_required
def new_variant(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        price = form_value('price', cast=float)
        if price is None:
            if wants_json():
                return api_error('Price required.', 422)
            flash('Price required.', 'danger')
            return render_template('admin/variant_form.html', product=product, variant=None)
        stock = form_value('stock', 0, cast=int) or 0
        variant = ProductVariant(product_id=product_id, price=price, stock=stock)
        _save_variant_fields(variant)
        variant.stock = stock
        db.session.add(variant)
        db.session.flush()
        db.session.add(InventoryLog(variant_id=variant.variant_id, change_type='IN',
                                    quantity=stock, reference='initial stock'))
        db.session.commit()
        flash('Variant added.', 'success')
        if wants_json():
            return api_ok(variant.to_dict(), status=201)
        return redirect(url_for('admin.variants', product_id=product_id))
    if wants_json():
        return api_error('POST volume/shade/sku/price/stock/expiry_date to add a variant.', 405)
    return render_template('admin/variant_form.html', product=product, variant=None)


@admin_bp.route('/variants/<int:variant_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_variant(variant_id):
    variant = ProductVariant.query.get_or_404(variant_id)
    product = variant.product
    if request.method == 'POST':
        old_stock = variant.stock
        _save_variant_fields(variant)
        new_stock = form_value('stock', 0, cast=int) or 0

        diff = new_stock - old_stock
        if diff != 0:
            db.session.add(InventoryLog(
                variant_id  = variant_id,
                change_type = 'IN' if diff > 0 else 'ADJUSTMENT',
                quantity    = abs(diff),
                reference   = 'admin edit'
            ))
        variant.stock = new_stock

        # Restocking a sold-out variant is what makes the alert list actionable.
        if old_stock == 0 and new_stock > 0:
            waiting = BackInStockAlert.query.filter_by(variant_id=variant_id,
                                                       notified_at=None).count()
            if waiting:
                flash(f'{waiting} customer(s) are waiting on this one — see Stock Alerts.',
                      'info')

        db.session.commit()
        flash('Variant updated.', 'success')
        if wants_json():
            return api_ok(variant.to_dict())
        return redirect(url_for('admin.variants', product_id=product.product_id))
    if wants_json():
        return api_ok(variant.to_dict())
    return render_template('admin/variant_form.html', product=product, variant=variant)


@admin_bp.route('/variants/<int:variant_id>/delete', methods=['POST'])
@admin_required
def delete_variant(variant_id):
    variant = ProductVariant.query.get_or_404(variant_id)
    product_id = variant.product_id
    db.session.delete(variant)
    db.session.commit()
    flash('Variant deleted.', 'info')
    if wants_json():
        return api_ok(message='Variant deleted.')
    return redirect(url_for('admin.variants', product_id=product_id))


# ── Bundles ────────────────────────────────────────────────────────────────────
@admin_bp.route('/bundles')
@admin_required
def bundles():
    items = Bundle.query.order_by(Bundle.name).all()
    if wants_json():
        return api_ok([b.to_dict() for b in items])
    return render_template('admin/bundles.html', bundles=items)


@admin_bp.route('/bundles/new', methods=['GET', 'POST'])
@admin_required
def new_bundle():
    if request.method == 'POST':
        name  = (form_value('name', '') or '').strip()
        price = form_value('price', cast=float)
        if not name or price is None:
            if wants_json():
                return api_error('Name and price are required.', 422)
            flash('Name and price are required.', 'danger')
            return render_template('admin/bundle_form.html', bundle=None)
        bundle = Bundle(
            name=name, slug=unique_slug(Bundle, name), price=price,
            description=(form_value('description', '') or '').strip() or None,
            image=(form_value('image', '') or '').strip() or None,
            is_active=True)
        db.session.add(bundle)
        db.session.commit()
        flash('Bundle created — now add the products it contains.', 'success')
        if wants_json():
            return api_ok(bundle.to_dict(), status=201)
        return redirect(url_for('admin.edit_bundle', bundle_id=bundle.bundle_id))
    if wants_json():
        return api_error('POST name/price/description to create a bundle.', 405)
    return render_template('admin/bundle_form.html', bundle=None)


@admin_bp.route('/bundles/<int:bundle_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_bundle(bundle_id):
    bundle = Bundle.query.get_or_404(bundle_id)
    if request.method == 'POST':
        new_name = (form_value('name', bundle.name) or '').strip()
        if new_name != bundle.name:
            bundle.slug = unique_slug(Bundle, new_name, pk_field='bundle_id',
                                      pk_value=bundle_id)
        bundle.name = new_name
        bundle.price = form_value('price', cast=float)
        bundle.description = (form_value('description', '') or '').strip() or None
        bundle.image = (form_value('image', '') or '').strip() or None
        bundle.is_active = _checkbox('is_active')
        db.session.commit()
        flash('Bundle updated.', 'success')
        if wants_json():
            return api_ok(bundle.to_dict())
        return redirect(url_for('admin.bundles'))
    if wants_json():
        return api_ok(bundle.to_dict())
    return render_template('admin/bundle_form.html', bundle=bundle,
                           all_variants=ProductVariant.query.join(Product)
                                        .order_by(Product.name).all())


@admin_bp.route('/bundles/<int:bundle_id>/items', methods=['POST'])
@admin_required
def add_bundle_item(bundle_id):
    bundle = Bundle.query.get_or_404(bundle_id)
    variant_id = form_value('variant_id', cast=int)
    quantity = max(1, form_value('quantity', 1, cast=int) or 1)
    if not variant_id:
        if wants_json():
            return api_error('Pick a product variant.', 422)
        flash('Pick a product variant.', 'danger')
        return redirect(url_for('admin.edit_bundle', bundle_id=bundle_id))
    existing = bundle.items.filter_by(variant_id=variant_id).first()
    if existing:
        existing.quantity = quantity
        item = existing
    else:
        item = BundleItem(bundle_id=bundle_id, variant_id=variant_id, quantity=quantity)
        db.session.add(item)
    db.session.commit()
    flash('Bundle contents updated.', 'success')
    if wants_json():
        return api_ok(item.to_dict(), status=201)
    return redirect(url_for('admin.edit_bundle', bundle_id=bundle_id))


@admin_bp.route('/bundles/<int:bundle_id>/items/<int:item_id>/delete', methods=['POST'])
@admin_required
def delete_bundle_item(bundle_id, item_id):
    item = BundleItem.query.get_or_404(item_id)
    if item.bundle_id != bundle_id:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    flash('Removed from bundle.', 'info')
    if wants_json():
        return api_ok(message='Removed from bundle.')
    return redirect(url_for('admin.edit_bundle', bundle_id=bundle_id))


@admin_bp.route('/bundles/<int:bundle_id>/delete', methods=['POST'])
@admin_required
def delete_bundle(bundle_id):
    bundle = Bundle.query.get_or_404(bundle_id)
    db.session.delete(bundle)
    db.session.commit()
    flash('Bundle deleted.', 'info')
    if wants_json():
        return api_ok(message='Bundle deleted.')
    return redirect(url_for('admin.bundles'))


# ── Shipping methods ───────────────────────────────────────────────────────────
@admin_bp.route('/shipping-methods')
@admin_required
def shipping_methods():
    items = ShippingMethod.query.order_by(ShippingMethod.sort_order,
                                          ShippingMethod.fee).all()
    if wants_json():
        return api_ok([m.to_dict() for m in items])
    return render_template('admin/shipping_methods.html', methods=items)


def _save_shipping_method(method):
    method.name        = (form_value('name', '') or '').strip()
    method.description = (form_value('description', '') or '').strip() or None
    method.fee         = form_value('fee', 0, cast=float) or 0
    free_over          = form_value('free_over', cast=float)
    method.free_over   = free_over if free_over else None
    method.eta_days_min = form_value('eta_days_min', 1, cast=int) or 1
    method.eta_days_max = form_value('eta_days_max', 5, cast=int) or 5
    method.sort_order   = form_value('sort_order', 0, cast=int) or 0
    method.is_active    = _checkbox('is_active')
    return bool(method.name)


@admin_bp.route('/shipping-methods/new', methods=['GET', 'POST'])
@admin_required
def new_shipping_method():
    if request.method == 'POST':
        method = ShippingMethod()
        if not _save_shipping_method(method):
            if wants_json():
                return api_error('Name required.', 422)
            flash('Name required.', 'danger')
            return render_template('admin/shipping_method_form.html', method=None)
        db.session.add(method)
        db.session.commit()
        flash('Shipping method created.', 'success')
        if wants_json():
            return api_ok(method.to_dict(), status=201)
        return redirect(url_for('admin.shipping_methods'))
    if wants_json():
        return api_error('POST name/fee/free_over/eta_days_min/eta_days_max.', 405)
    return render_template('admin/shipping_method_form.html', method=None)


@admin_bp.route('/shipping-methods/<int:method_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_shipping_method(method_id):
    method = ShippingMethod.query.get_or_404(method_id)
    if request.method == 'POST':
        if not _save_shipping_method(method):
            if wants_json():
                return api_error('Name required.', 422)
            flash('Name required.', 'danger')
            return render_template('admin/shipping_method_form.html', method=method)
        db.session.commit()
        flash('Shipping method updated.', 'success')
        if wants_json():
            return api_ok(method.to_dict())
        return redirect(url_for('admin.shipping_methods'))
    if wants_json():
        return api_ok(method.to_dict())
    return render_template('admin/shipping_method_form.html', method=method)


@admin_bp.route('/shipping-methods/<int:method_id>/delete', methods=['POST'])
@admin_required
def delete_shipping_method(method_id):
    method = ShippingMethod.query.get_or_404(method_id)
    if method.orders.count():
        msg = 'This method is attached to existing orders — deactivate it instead.'
        if wants_json():
            return api_error(msg, 409)
        flash(msg, 'warning')
        return redirect(url_for('admin.shipping_methods'))
    db.session.delete(method)
    db.session.commit()
    flash('Shipping method deleted.', 'info')
    if wants_json():
        return api_ok(message='Shipping method deleted.')
    return redirect(url_for('admin.shipping_methods'))


# ── Orders ─────────────────────────────────────────────────────────────────────
@admin_bp.route('/orders')
@admin_required
def orders():
    status = request.args.get('status', '')
    query  = Order.query.order_by(Order.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    orders = query.all()
    if wants_json():
        return api_ok({
            'orders': [o.to_dict(include_items=False) for o in orders],
            'current_status': status,
            'statuses': Order.STATUS_CHOICES,
        })
    return render_template('admin/orders.html', orders=orders,
                           current_status=status, statuses=Order.STATUS_CHOICES)


@admin_bp.route('/orders/<int:order_id>')
@admin_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    if wants_json():
        return api_ok({'order': order.to_dict(), 'statuses': Order.STATUS_CHOICES})
    return render_template('admin/order_detail.html', order=order,
                           statuses=Order.STATUS_CHOICES)


@admin_bp.route('/orders/<int:order_id>/update-status', methods=['POST'])
@admin_required
def update_order_status(order_id):
    order  = Order.query.get_or_404(order_id)
    status = form_value('status')
    note   = (form_value('note', '') or '').strip() or None
    if status not in Order.STATUS_CHOICES:
        if wants_json():
            return api_error('Invalid status.', 422, statuses=Order.STATUS_CHOICES)
        flash('Invalid status.', 'danger')
        return redirect(url_for('admin.order_detail', order_id=order_id))

    order.set_status(status, note=note, changed_by=current_user.user_id)

    if order.payment and status == 'Delivered':
        order.payment.status = 'Paid'
        order.payment.paid_at = order.payment.paid_at or datetime.utcnow()
    if order.shipping:
        if status == 'Shipped':
            order.shipping.status = 'Shipped'
            order.shipping.shipped_at = order.shipping.shipped_at or datetime.utcnow()
        elif status == 'Delivered':
            order.shipping.status = 'Delivered'
            order.shipping.delivered_at = order.shipping.delivered_at or datetime.utcnow()

    # Cancelling puts the stock back.
    if status == 'Cancelled':
        for item in order.items:
            if item.variant:
                item.variant.stock += item.quantity
                db.session.add(InventoryLog(
                    variant_id=item.variant_id, change_type='IN', quantity=item.quantity,
                    reference=f'order_{order_id} cancelled'))

    db.session.commit()
    flash(f'Order #{order_id} status updated to {status}.', 'success')
    if wants_json():
        return api_ok(order.to_dict())
    return redirect(url_for('admin.order_detail', order_id=order_id))


@admin_bp.route('/orders/<int:order_id>/tracking', methods=['POST'])
@admin_required
def update_tracking(order_id):
    order = Order.query.get_or_404(order_id)
    if not order.shipping:
        if wants_json():
            return api_error('This order has no shipping record.', 404)
        flash('This order has no shipping record.', 'warning')
        return redirect(url_for('admin.order_detail', order_id=order_id))
    order.shipping.carrier = (form_value('carrier', '') or '').strip() or None
    order.shipping.tracking_number = (form_value('tracking_number', '') or '').strip() or None
    db.session.commit()
    flash('Tracking details saved.', 'success')
    if wants_json():
        return api_ok(order.shipping.to_dict())
    return redirect(url_for('admin.order_detail', order_id=order_id))


# ── Returns ────────────────────────────────────────────────────────────────────
@admin_bp.route('/returns')
@admin_required
def returns():
    status = request.args.get('status', '')
    query = ReturnRequest.query.order_by(ReturnRequest.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    items = query.all()
    if wants_json():
        return api_ok({'returns': [r.to_dict() for r in items],
                       'statuses': ReturnRequest.STATUS_CHOICES,
                       'current_status': status})
    return render_template('admin/returns.html', returns=items,
                           statuses=ReturnRequest.STATUS_CHOICES,
                           current_status=status)


@admin_bp.route('/returns/<int:return_id>', methods=['GET', 'POST'])
@admin_required
def return_detail(return_id):
    req = ReturnRequest.query.get_or_404(return_id)
    if request.method == 'POST':
        status = form_value('status')
        if status not in ReturnRequest.STATUS_CHOICES:
            if wants_json():
                return api_error('Invalid status.', 422,
                                 statuses=ReturnRequest.STATUS_CHOICES)
            flash('Invalid status.', 'danger')
            return redirect(url_for('admin.return_detail', return_id=return_id))

        refund = form_value('refund_amount', cast=float)
        if refund is not None:
            req.refund_amount = refund

        was_restocked = req.status in ('Received', 'Refunded')
        req.status = status
        if status in ('Received', 'Refunded') and not was_restocked:
            # Opened skincare usually cannot be resold — log it as an adjustment
            # rather than silently pushing it back into sellable stock.
            for item in req.items:
                variant = item.order_item.variant
                if variant:
                    db.session.add(InventoryLog(
                        variant_id=variant.variant_id, change_type='ADJUSTMENT',
                        quantity=item.quantity,
                        reference=f'return_{req.return_id} received (not resellable)'))
        if status == 'Refunded':
            req.resolved_at = datetime.utcnow()
            order_payment = req.order.payment
            if order_payment:
                order_payment.status = 'Refunded'
        elif status == 'Rejected':
            req.resolved_at = datetime.utcnow()

        db.session.commit()
        flash(f'Return #{return_id} marked {status}.', 'success')
        if wants_json():
            return api_ok(req.to_dict())
        return redirect(url_for('admin.return_detail', return_id=return_id))

    if wants_json():
        return api_ok({'return': req.to_dict(),
                       'statuses': ReturnRequest.STATUS_CHOICES})
    return render_template('admin/return_detail.html', req=req,
                           statuses=ReturnRequest.STATUS_CHOICES)


# ── Stock alerts ───────────────────────────────────────────────────────────────
@admin_bp.route('/stock-alerts')
@admin_required
def stock_alerts():
    items = (BackInStockAlert.query.filter_by(notified_at=None)
             .order_by(BackInStockAlert.created_at.desc()).all())
    # Group by variant so the buyer sees demand, not a flat list of emails.
    grouped = {}
    for alert in items:
        grouped.setdefault(alert.variant_id, {'variant': alert.variant, 'alerts': []})
        grouped[alert.variant_id]['alerts'].append(alert)
    ordered = sorted(grouped.values(), key=lambda g: len(g['alerts']), reverse=True)
    if wants_json():
        return api_ok([{'variant': g['variant'].to_dict(),
                        'waiting': len(g['alerts']),
                        'emails': [a.email for a in g['alerts']]} for g in ordered])
    total_waiting = sum(len(g['alerts']) for g in ordered)
    return render_template('admin/stock_alerts.html', groups=ordered, total_waiting=total_waiting)


@admin_bp.route('/stock-alerts/variant/<int:variant_id>/notify', methods=['POST'])
@admin_required
def notify_stock_alerts(variant_id):
    """Mark everyone waiting on this variant as notified.

    Sending the actual email needs a mail backend, which this app does not have
    yet — this records that the notification went out.
    """
    variant = ProductVariant.query.get_or_404(variant_id)
    pending = BackInStockAlert.query.filter_by(variant_id=variant_id, notified_at=None).all()
    for alert in pending:
        alert.notified_at = datetime.utcnow()
    db.session.commit()
    flash(f'Marked {len(pending)} alert(s) for "{variant.product.name}" as notified.', 'success')
    if wants_json():
        return api_ok({'notified': len(pending)})
    return redirect(url_for('admin.stock_alerts'))


# ── Subscriptions ──────────────────────────────────────────────────────────────
@admin_bp.route('/subscriptions')
@admin_required
def subscriptions():
    items = Subscription.query.order_by(Subscription.next_delivery_at.asc().nulls_last()).all()
    due = [s for s in items
           if s.status == 'Active' and s.next_delivery_at
           and s.next_delivery_at <= datetime.utcnow() + timedelta(days=7)]
    if wants_json():
        return api_ok({'subscriptions': [s.to_dict() for s in items],
                       'due_within_7_days': [s.to_dict() for s in due]})
    return render_template('admin/subscriptions.html', subscriptions=items, due=due)


# ── Coupons ────────────────────────────────────────────────────────────────────
@admin_bp.route('/coupons')
@admin_required
def coupons():
    coupons = Coupon.query.all()
    if wants_json():
        return api_ok([c.to_dict() for c in coupons])
    return render_template('admin/coupons.html', coupons=coupons)


@admin_bp.route('/coupons/new', methods=['GET', 'POST'])
@admin_required
def new_coupon():
    if request.method == 'POST':
        code  = (form_value('code', '') or '').strip().upper()
        dtype = form_value('discount_type')
        dval  = form_value('discount_value', cast=float)
        mina  = form_value('min_amount', 0, cast=float)
        exp   = form_value('expiry_date')
        expiry = datetime.strptime(exp, '%Y-%m-%d') if exp else None
        coupon = Coupon(code=code, discount_type=dtype, discount_value=dval,
                        min_amount=mina, expiry_date=expiry)
        db.session.add(coupon)
        db.session.commit()
        flash('Coupon created.', 'success')
        if wants_json():
            return api_ok(coupon.to_dict(), status=201)
        return redirect(url_for('admin.coupons'))
    if wants_json():
        return api_error('POST code/discount_type/discount_value/min_amount/expiry_date to create a coupon.', 405)
    return render_template('admin/coupon_form.html', coupon=None)


@admin_bp.route('/coupons/<int:coupon_id>/delete', methods=['POST'])
@admin_required
def delete_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    db.session.delete(coupon)
    db.session.commit()
    flash('Coupon deleted.', 'info')
    if wants_json():
        return api_ok(message='Coupon deleted.')
    return redirect(url_for('admin.coupons'))


# ── Promotions ─────────────────────────────────────────────────────────────────
@admin_bp.route('/promotions')
@admin_required
def promotions():
    promos = Promotion.query.all()
    if wants_json():
        return api_ok([p.to_dict() for p in promos])
    return render_template('admin/promotions.html', promotions=promos)


@admin_bp.route('/promotions/new', methods=['GET', 'POST'])
@admin_required
def new_promotion():
    products = Product.query.order_by(Product.name).all()
    if request.method == 'POST':
        name    = (form_value('name', '') or '').strip()
        disc    = form_value('discount_percent', cast=float)
        start   = form_value('start_date')
        end     = form_value('end_date')
        p_ids   = form_list('product_ids', cast=int)
        promo = Promotion(
            name             = name,
            discount_percent = disc,
            start_date       = datetime.strptime(start, '%Y-%m-%d'),
            end_date         = datetime.strptime(end,   '%Y-%m-%d')
        )
        db.session.add(promo)
        db.session.flush()
        for pid in p_ids:
            p = Product.query.get(pid)
            if p:
                promo.products.append(p)
        db.session.commit()
        flash('Promotion created.', 'success')
        if wants_json():
            return api_ok(promo.to_dict(), status=201)
        return redirect(url_for('admin.promotions'))
    if wants_json():
        return api_error('POST name/discount_percent/start_date/end_date/product_ids to create a promotion.', 405)
    return render_template('admin/promotion_form.html', promotion=None, products=products)


@admin_bp.route('/promotions/<int:promo_id>/delete', methods=['POST'])
@admin_required
def delete_promotion(promo_id):
    promo = Promotion.query.get_or_404(promo_id)
    db.session.delete(promo)
    db.session.commit()
    flash('Promotion deleted.', 'info')
    if wants_json():
        return api_ok(message='Promotion deleted.')
    return redirect(url_for('admin.promotions'))


# ── Inventory ──────────────────────────────────────────────────────────────────
@admin_bp.route('/inventory')
@admin_required
def inventory():
    logs = InventoryLog.query.order_by(InventoryLog.created_at.desc()).limit(200).all()
    low_stock = (ProductVariant.query
                 .filter(ProductVariant.stock <= LOW_STOCK_THRESHOLD)
                 .order_by(ProductVariant.stock.asc()).all())
    expiry_cutoff = (datetime.utcnow() + timedelta(days=EXPIRY_WARNING_DAYS)).date()
    expiring = (ProductVariant.query
                .filter(ProductVariant.expiry_date.isnot(None),
                        ProductVariant.expiry_date <= expiry_cutoff)
                .order_by(ProductVariant.expiry_date.asc()).all())
    if wants_json():
        return api_ok({
            'logs': [l.to_dict() for l in logs],
            'low_stock': [v.to_dict() for v in low_stock],
            'expiring': [v.to_dict() for v in expiring],
        })
    return render_template('admin/inventory.html', logs=logs,
                           low_stock=low_stock, expiring=expiring,
                           threshold=LOW_STOCK_THRESHOLD,
                           expiry_days=EXPIRY_WARNING_DAYS)


# ── Bakong Merchants ───────────────────────────────────────────────────────────
@admin_bp.route('/bakong-merchants')
@admin_required
def bakong_merchants():
    merchants = BakongMerchant.query.order_by(BakongMerchant.created_at.desc()).all()
    if wants_json():
        return api_ok([m.to_dict() for m in merchants])
    return render_template('admin/bakong_merchants.html', merchants=merchants)


@admin_bp.route('/bakong-merchants/new', methods=['GET', 'POST'])
@admin_required
def new_bakong_merchant():
    if request.method == 'POST':
        merchant_name = (form_value('merchant_name', '') or '').strip()
        bank_account  = (form_value('bank_account', '') or '').strip()
        merchant_city = (form_value('merchant_city', '') or '').strip()
        terminal_label= (form_value('terminal_label', '') or '').strip()
        if not all([merchant_name, bank_account, merchant_city, terminal_label]):
            if wants_json():
                return api_error('All fields required.', 422)
            flash('All fields required.', 'danger')
            return render_template('admin/bakong_merchant_form.html', merchant=None)
        merchant = BakongMerchant(
            merchant_name=merchant_name,
            bank_account=bank_account,
            merchant_city=merchant_city,
            terminal_label=terminal_label
        )
        db.session.add(merchant)
        db.session.commit()
        flash('Bakong merchant created.', 'success')
        if wants_json():
            return api_ok(merchant.to_dict(), status=201)
        return redirect(url_for('admin.bakong_merchants'))
    if wants_json():
        return api_error('POST merchant_name/bank_account/merchant_city/terminal_label to create a merchant.', 405)
    return render_template('admin/bakong_merchant_form.html', merchant=None)


@admin_bp.route('/bakong-merchants/<int:merchant_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_bakong_merchant(merchant_id):
    merchant = BakongMerchant.query.get_or_404(merchant_id)
    if request.method == 'POST':
        merchant.merchant_name = (form_value('merchant_name', merchant.merchant_name) or '').strip()
        merchant.bank_account  = (form_value('bank_account', merchant.bank_account) or '').strip()
        merchant.merchant_city = (form_value('merchant_city', merchant.merchant_city) or '').strip()
        merchant.terminal_label= (form_value('terminal_label', merchant.terminal_label) or '').strip()
        merchant.is_active     = _checkbox('is_active')
        db.session.commit()
        flash('Bakong merchant updated.', 'success')
        if wants_json():
            return api_ok(merchant.to_dict())
        return redirect(url_for('admin.bakong_merchants'))
    if wants_json():
        return api_ok(merchant.to_dict())
    return render_template('admin/bakong_merchant_form.html', merchant=merchant)


@admin_bp.route('/bakong-merchants/<int:merchant_id>/delete', methods=['POST'])
@admin_required
def delete_bakong_merchant(merchant_id):
    merchant = BakongMerchant.query.get_or_404(merchant_id)
    db.session.delete(merchant)
    db.session.commit()
    flash('Bakong merchant deleted.', 'info')
    if wants_json():
        return api_ok(message='Bakong merchant deleted.')
    return redirect(url_for('admin.bakong_merchants'))


# ── Payment Transactions ───────────────────────────────────────────────────────
@admin_bp.route('/payment-transactions')
@admin_required
def payment_transactions():
    transactions = PaymentTransaction.query.order_by(PaymentTransaction.created_at.desc()).all()
    if wants_json():
        return api_ok([t.to_dict() for t in transactions])
    return render_template('admin/payment_transactions.html', transactions=transactions)


@admin_bp.route('/payment-transactions/check-bulk', methods=['POST'])
@admin_required
def check_bulk_payments():
    bakong_token = current_app.config.get('BAKONG_TOKEN')
    if not bakong_token:
        if wants_json():
            return api_error('Bakong token not configured.', 500)
        flash('Bakong token not configured.', 'danger')
        return redirect(url_for('admin.payment_transactions'))

    url = 'https://api-bakong.nbc.gov.kh/v1/check_transaction_by_md5'
    headers = {
        'Authorization': f'Bearer {bakong_token}',
        'Content-Type': 'application/json'
    }

    updated = 0
    pending = PaymentTransaction.query.filter_by(status='Pending').all()

    for tx in pending:
        payload = {'md5': tx.md5_hash}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            result = response.json()

            if response.status_code == 200 and result.get('responseCode') == 0:
                tx.status = 'Paid'
                tx.paid_at = datetime.utcnow()
                if tx.order and tx.order.payment:
                    tx.order.payment.status = 'Paid'
                    tx.order.payment.paid_at = datetime.utcnow()
                updated += 1
        except Exception:
            # Network hiccup on one transaction shouldn't stop the sweep.
            pass

    if updated > 0:
        db.session.commit()
        flash(f'Updated {updated} payment(s).', 'success')
    else:
        flash('No payments updated.', 'info')

    if wants_json():
        return api_ok({'updated': updated})
    return redirect(url_for('admin.payment_transactions'))


@admin_bp.route('/payment-transactions/<int:tx_id>/download-qr')
@admin_required
def download_qr(tx_id):
    tx = PaymentTransaction.query.get_or_404(tx_id)

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(tx.qr_string)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    return send_file(buffer, mimetype='image/png',
                     download_name=f'khqr_payment_{tx.transaction_id}.png')
