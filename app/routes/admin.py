from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, send_file, current_app
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime
from app.models import (db, User, Role, Category, Product, ProductVariant,
                        Order, Payment, Shipping, Coupon, Promotion,
                        InventoryLog, Review, BakongMerchant, PaymentTransaction)
import hashlib
from bakong_khqr import KHQR
import qrcode
import io
import requests

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return login_required(decorated)


# ── Dashboard ──────────────────────────────────────────────────────────────────
@admin_bp.route('/')
@admin_required
def dashboard():
    stats = {
        'users':    User.query.count(),
        'products': Product.query.count(),
        'orders':   Order.query.count(),
        'revenue':  db.session.query(db.func.sum(Order.total_amount))
                              .filter(Order.status == 'Delivered').scalar() or 0,
    }
    recent_orders  = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    order_statuses = {s: Order.query.filter_by(status=s).count()
                      for s in Order.STATUS_CHOICES}
    return render_template('admin/dashboard.html',
                           stats=stats,
                           recent_orders=recent_orders,
                           order_statuses=order_statuses)


# ── Users ──────────────────────────────────────────────────────────────────────
@admin_bp.route('/users')
@admin_required
def users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)


@admin_bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.user_id == current_user.user_id:
        flash("Cannot modify your own role.", 'warning')
        return redirect(url_for('admin.users'))
    admin_role = Role.query.filter_by(role_name='Admin').first()
    if not admin_role:
        admin_role = Role(role_name='Admin')
        db.session.add(admin_role)
    if user.has_role('Admin'):
        user.roles.remove(admin_role)
        flash(f'{user.name} is no longer Admin.', 'info')
    else:
        user.roles.append(admin_role)
        flash(f'{user.name} is now Admin.', 'success')
    db.session.commit()
    return redirect(url_for('admin.users'))


# ── Categories ─────────────────────────────────────────────────────────────────
@admin_bp.route('/categories')
@admin_required
def categories():
    cats = Category.query.all()
    return render_template('admin/categories.html', categories=cats)


@admin_bp.route('/categories/new', methods=['GET', 'POST'])
@admin_required
def new_category():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        desc = request.form.get('description', '').strip()
        if not name:
            flash('Name required.', 'danger')
            return render_template('admin/category_form.html', category=None)
        cat = Category(name=name, description=desc)
        db.session.add(cat)
        db.session.commit()
        flash('Category created.', 'success')
        return redirect(url_for('admin.categories'))
    return render_template('admin/category_form.html', category=None)


@admin_bp.route('/categories/<int:cat_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    if request.method == 'POST':
        cat.name        = request.form.get('name', cat.name).strip()
        cat.description = request.form.get('description', '').strip()
        db.session.commit()
        flash('Category updated.', 'success')
        return redirect(url_for('admin.categories'))
    return render_template('admin/category_form.html', category=cat)


@admin_bp.route('/categories/<int:cat_id>/delete', methods=['POST'])
@admin_required
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    db.session.delete(cat)
    db.session.commit()
    flash('Category deleted.', 'info')
    return redirect(url_for('admin.categories'))


# ── Products ───────────────────────────────────────────────────────────────────
@admin_bp.route('/products')
@admin_required
def products():
    prods = Product.query.order_by(Product.created_at.desc()).all()
    return render_template('admin/products.html', products=prods)


@admin_bp.route('/products/new', methods=['GET', 'POST'])
@admin_required
def new_product():
    categories = Category.query.all()
    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        cat_id      = request.form.get('category_id', type=int)
        description = request.form.get('description', '').strip()
        base_price  = request.form.get('base_price', type=float)
        if not name or not cat_id or base_price is None:
            flash('All fields required.', 'danger')
            return render_template('admin/product_form.html', product=None, categories=categories)
        product = Product(name=name, category_id=cat_id,
                          description=description, base_price=base_price)
        db.session.add(product)
        db.session.commit()
        flash('Product created.', 'success')
        return redirect(url_for('admin.products'))
    return render_template('admin/product_form.html', product=None, categories=categories)


@admin_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_product(product_id):
    product    = Product.query.get_or_404(product_id)
    categories = Category.query.all()
    if request.method == 'POST':
        product.name        = request.form.get('name', product.name).strip()
        product.category_id = request.form.get('category_id', type=int)
        product.description = request.form.get('description', '').strip()
        product.base_price  = request.form.get('base_price', type=float)
        db.session.commit()
        flash('Product updated.', 'success')
        return redirect(url_for('admin.products'))
    return render_template('admin/product_form.html', product=product, categories=categories)


@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@admin_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'info')
    return redirect(url_for('admin.products'))


# ── Variants ───────────────────────────────────────────────────────────────────
@admin_bp.route('/products/<int:product_id>/variants')
@admin_required
def variants(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('admin/variants.html', product=product)


@admin_bp.route('/products/<int:product_id>/variants/new', methods=['GET', 'POST'])
@admin_required
def new_variant(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        size  = request.form.get('size', '').strip()
        color = request.form.get('color', '').strip()
        price = request.form.get('price', type=float)
        stock = request.form.get('stock', 0, type=int)
        image = request.form.get('image', '').strip()
        if price is None:
            flash('Price required.', 'danger')
            return render_template('admin/variant_form.html', product=product, variant=None)
        variant = ProductVariant(product_id=product_id, size=size, color=color,
                                 price=price, stock=stock, image=image)
        db.session.add(variant)
        db.session.flush()
        log = InventoryLog(variant_id=variant.variant_id, change_type='IN',
                           quantity=stock, reference='initial stock')
        db.session.add(log)
        db.session.commit()
        flash('Variant added.', 'success')
        return redirect(url_for('admin.variants', product_id=product_id))
    return render_template('admin/variant_form.html', product=product, variant=None)


@admin_bp.route('/variants/<int:variant_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_variant(variant_id):
    variant = ProductVariant.query.get_or_404(variant_id)
    product = variant.product
    if request.method == 'POST':
        old_stock    = variant.stock
        variant.size  = request.form.get('size', '').strip()
        variant.color = request.form.get('color', '').strip()
        variant.price = request.form.get('price', type=float)
        new_stock     = request.form.get('stock', 0, type=int)
        variant.image = request.form.get('image', '').strip()

        diff = new_stock - old_stock
        if diff != 0:
            log = InventoryLog(
                variant_id  = variant_id,
                change_type = 'IN' if diff > 0 else 'ADJUSTMENT',
                quantity    = abs(diff),
                reference   = 'admin edit'
            )
            db.session.add(log)
        variant.stock = new_stock
        db.session.commit()
        flash('Variant updated.', 'success')
        return redirect(url_for('admin.variants', product_id=product.product_id))
    return render_template('admin/variant_form.html', product=product, variant=variant)


@admin_bp.route('/variants/<int:variant_id>/delete', methods=['POST'])
@admin_required
def delete_variant(variant_id):
    variant = ProductVariant.query.get_or_404(variant_id)
    product_id = variant.product_id
    db.session.delete(variant)
    db.session.commit()
    flash('Variant deleted.', 'info')
    return redirect(url_for('admin.variants', product_id=product_id))


# ── Orders ─────────────────────────────────────────────────────────────────────
@admin_bp.route('/orders')
@admin_required
def orders():
    status = request.args.get('status', '')
    query  = Order.query.order_by(Order.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    orders = query.all()
    return render_template('admin/orders.html', orders=orders,
                           current_status=status, statuses=Order.STATUS_CHOICES)


@admin_bp.route('/orders/<int:order_id>')
@admin_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('admin/order_detail.html', order=order,
                           statuses=Order.STATUS_CHOICES)


@admin_bp.route('/orders/<int:order_id>/update-status', methods=['POST'])
@admin_required
def update_order_status(order_id):
    order  = Order.query.get_or_404(order_id)
    status = request.form.get('status')
    if status in Order.STATUS_CHOICES:
        order.status = status
        if order.payment and status == 'Delivered':
            order.payment.status = 'Paid'
            order.payment.paid_at = datetime.utcnow()
        if order.shipping:
            if status == 'Shipped':
                order.shipping.status = 'Shipped'
            elif status == 'Delivered':
                order.shipping.status = 'Delivered'
        db.session.commit()
        flash(f'Order #{order_id} status updated to {status}.', 'success')
    return redirect(url_for('admin.order_detail', order_id=order_id))


# ── Coupons ────────────────────────────────────────────────────────────────────
@admin_bp.route('/coupons')
@admin_required
def coupons():
    coupons = Coupon.query.all()
    return render_template('admin/coupons.html', coupons=coupons)


@admin_bp.route('/coupons/new', methods=['GET', 'POST'])
@admin_required
def new_coupon():
    if request.method == 'POST':
        code  = request.form.get('code', '').strip().upper()
        dtype = request.form.get('discount_type')
        dval  = request.form.get('discount_value', type=float)
        mina  = request.form.get('min_amount', 0, type=float)
        exp   = request.form.get('expiry_date')
        expiry = datetime.strptime(exp, '%Y-%m-%d') if exp else None
        coupon = Coupon(code=code, discount_type=dtype, discount_value=dval,
                        min_amount=mina, expiry_date=expiry)
        db.session.add(coupon)
        db.session.commit()
        flash('Coupon created.', 'success')
        return redirect(url_for('admin.coupons'))
    return render_template('admin/coupon_form.html', coupon=None)


@admin_bp.route('/coupons/<int:coupon_id>/delete', methods=['POST'])
@admin_required
def delete_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    db.session.delete(coupon)
    db.session.commit()
    flash('Coupon deleted.', 'info')
    return redirect(url_for('admin.coupons'))


# ── Promotions ─────────────────────────────────────────────────────────────────
@admin_bp.route('/promotions')
@admin_required
def promotions():
    promos = Promotion.query.all()
    return render_template('admin/promotions.html', promotions=promos)


@admin_bp.route('/promotions/new', methods=['GET', 'POST'])
@admin_required
def new_promotion():
    products = Product.query.all()
    if request.method == 'POST':
        name    = request.form.get('name', '').strip()
        disc    = request.form.get('discount_percent', type=float)
        start   = request.form.get('start_date')
        end     = request.form.get('end_date')
        p_ids   = request.form.getlist('product_ids', type=int)
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
        return redirect(url_for('admin.promotions'))
    return render_template('admin/promotion_form.html', promotion=None, products=products)


@admin_bp.route('/promotions/<int:promo_id>/delete', methods=['POST'])
@admin_required
def delete_promotion(promo_id):
    promo = Promotion.query.get_or_404(promo_id)
    db.session.delete(promo)
    db.session.commit()
    flash('Promotion deleted.', 'info')
    return redirect(url_for('admin.promotions'))


# ── Inventory ──────────────────────────────────────────────────────────────────
@admin_bp.route('/inventory')
@admin_required
def inventory():
    logs = InventoryLog.query.order_by(InventoryLog.created_at.desc()).limit(200).all()
    return render_template('admin/inventory.html', logs=logs)


# ── Bakong Merchants ───────────────────────────────────────────────────────────
@admin_bp.route('/bakong-merchants')
@admin_required
def bakong_merchants():
    merchants = BakongMerchant.query.order_by(BakongMerchant.created_at.desc()).all()
    return render_template('admin/bakong_merchants.html', merchants=merchants)


@admin_bp.route('/bakong-merchants/new', methods=['GET', 'POST'])
@admin_required
def new_bakong_merchant():
    if request.method == 'POST':
        merchant_name = request.form.get('merchant_name', '').strip()
        bank_account  = request.form.get('bank_account', '').strip()
        merchant_city = request.form.get('merchant_city', '').strip()
        terminal_label= request.form.get('terminal_label', '').strip()
        if not all([merchant_name, bank_account, merchant_city, terminal_label]):
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
        return redirect(url_for('admin.bakong_merchants'))
    return render_template('admin/bakong_merchant_form.html', merchant=None)


@admin_bp.route('/bakong-merchants/<int:merchant_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_bakong_merchant(merchant_id):
    merchant = BakongMerchant.query.get_or_404(merchant_id)
    if request.method == 'POST':
        merchant.merchant_name = request.form.get('merchant_name', merchant.merchant_name).strip()
        merchant.bank_account  = request.form.get('bank_account', merchant.bank_account).strip()
        merchant.merchant_city = request.form.get('merchant_city', merchant.merchant_city).strip()
        merchant.terminal_label= request.form.get('terminal_label', merchant.terminal_label).strip()
        merchant.is_active     = 'is_active' in request.form
        db.session.commit()
        flash('Bakong merchant updated.', 'success')
        return redirect(url_for('admin.bakong_merchants'))
    return render_template('admin/bakong_merchant_form.html', merchant=merchant)


@admin_bp.route('/bakong-merchants/<int:merchant_id>/delete', methods=['POST'])
@admin_required
def delete_bakong_merchant(merchant_id):
    merchant = BakongMerchant.query.get_or_404(merchant_id)
    db.session.delete(merchant)
    db.session.commit()
    flash('Bakong merchant deleted.', 'info')
    return redirect(url_for('admin.bakong_merchants'))


# ── Payment Transactions ───────────────────────────────────────────────────────
@admin_bp.route('/payment-transactions')
@admin_required
def payment_transactions():
    transactions = PaymentTransaction.query.order_by(PaymentTransaction.created_at.desc()).all()
    return render_template('admin/payment_transactions.html', transactions=transactions)


@admin_bp.route('/payment-transactions/check-bulk', methods=['POST'])
@admin_required
def check_bulk_payments():
    bakong_token = current_app.config.get('BAKONG_TOKEN')
    if not bakong_token:
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
                # Payment successful
                tx.status = 'Paid'
                tx.paid_at = datetime.utcnow()
                tx.order.payment.status = 'Paid'
                tx.order.payment.paid_at = datetime.utcnow()
                updated += 1
            # For failed, maybe check responseCode or other fields
        except Exception as e:
            # Log error but continue
            pass

    if updated > 0:
        db.session.commit()
        flash(f'Updated {updated} payment(s).', 'success')
    else:
        flash('No payments updated.', 'info')

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
