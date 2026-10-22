from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from datetime import datetime
from app.models import (db, Cart, CartItem, Order, OrderItem, OrderStatusHistory,
                        Payment, Shipping, Coupon, InventoryLog, ShippingMethod,
                        Address, PaymentTransaction, BakongMerchant, Notification)
from app.api import wants_json, api_ok, api_error, form_value
import hashlib
from bakong_khqr import KHQR
import requests

orders_bp = Blueprint('orders', __name__)


def _shipping_methods():
    return ShippingMethod.query.filter_by(is_active=True)\
                               .order_by(ShippingMethod.sort_order, ShippingMethod.fee).all()


def _quote(cart, coupon=None, method=None):
    """Single source of truth for order money. Returns the full breakdown so the
    checkout page, the JSON API and the placed Order all agree."""
    subtotal = round(float(cart.total()), 2)
    discount = round(subtotal - float(coupon.apply(subtotal)), 2) if coupon else 0.0
    after_discount = round(subtotal - discount, 2)
    shipping_fee = round(method.fee_for(after_discount), 2) if method else 0.0
    tax_rate = float(current_app.config.get('TAX_RATE', 0) or 0)
    tax = round(after_discount * tax_rate, 2)
    total = round(after_discount + shipping_fee + tax, 2)
    return {
        'subtotal': subtotal,
        'discount': discount,
        'shipping_fee': shipping_fee,
        'tax': tax,
        'total': total,
    }


@orders_bp.route('/')
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=current_user.user_id)\
                  .order_by(Order.created_at.desc()).all()
    if wants_json():
        return api_ok([o.to_dict(include_items=False) for o in orders])
    return render_template('orders/list.html', orders=orders)


@orders_bp.route('/<int:order_id>')
@login_required
def detail(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.user_id and not current_user.is_admin():
        if wants_json():
            return api_error('Not authorised.', 403)
        flash('Not authorised.', 'danger')
        return redirect(url_for('orders.my_orders'))
    if wants_json():
        return api_ok(order.to_dict())
    return render_template('orders/detail.html', order=order)


@orders_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart = Cart.query.filter_by(user_id=current_user.user_id).first()
    if not cart or cart.items.count() == 0:
        if wants_json():
            return api_error('Your cart is empty.', 422)
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('cart.view_cart'))

    methods   = _shipping_methods()
    addresses = current_user.addresses.order_by(Address.is_default.desc()).all()
    default_method = methods[0] if methods else None

    coupon      = None
    coupon_code = ''

    def render_checkout(coupon, method, code=''):
        quote = _quote(cart, coupon, method)
        return render_template('orders/checkout.html', cart=cart, coupon=coupon,
                               coupon_code=code, quote=quote, methods=methods,
                               addresses=addresses,
                               selected_method_id=method.method_id if method else None)

    if request.method == 'POST':
        action = form_value('action')
        method_id = form_value('shipping_method_id', cast=int)
        method = ShippingMethod.query.get(method_id) if method_id else default_method

        # ── Re-price after a delivery-method change ────────────────────────────
        # Same render path as the coupon branch, but silent: an empty code here
        # is normal, not an error the customer should see.
        if action == 'update_shipping':
            coupon_code = (form_value('coupon_code', '') or '').strip().upper()
            coupon = Coupon.query.filter_by(code=coupon_code).first() if coupon_code else None
            if coupon and (not coupon.is_valid()
                           or float(cart.total()) < float(coupon.min_amount)):
                coupon = None
            if wants_json():
                return api_ok({'coupon': coupon.to_dict() if coupon else None,
                               'coupon_code': coupon_code,
                               **_quote(cart, coupon, method)})
            return render_checkout(coupon, method, coupon_code)

        # ── Apply coupon ───────────────────────────────────────────────────────
        if action == 'apply_coupon':
            coupon_code = (form_value('coupon_code', '') or '').strip().upper()
            coupon = Coupon.query.filter_by(code=coupon_code).first()
            if not coupon or not coupon.is_valid():
                if wants_json():
                    return api_error('Invalid or expired coupon.', 422)
                flash('Invalid or expired coupon.', 'danger')
                coupon = None
            elif float(cart.total()) < float(coupon.min_amount):
                msg = f'Minimum order amount for this coupon is ${coupon.min_amount}.'
                if wants_json():
                    return api_error(msg, 422)
                flash(msg, 'warning')
                coupon = None
            else:
                quote = _quote(cart, coupon, method)
                flash(f'Coupon applied! You saved ${quote["discount"]:.2f}.', 'success')
            if wants_json():
                return api_ok({'coupon': coupon.to_dict() if coupon else None,
                               'coupon_code': coupon_code,
                               **_quote(cart, coupon, method)})
            return render_checkout(coupon, method, coupon_code)

        # ── Place order ────────────────────────────────────────────────────────
        if action == 'place_order':
            payment_method = form_value('payment_method', 'Cash')
            coupon_id  = form_value('coupon_id', cast=int)
            coupon     = Coupon.query.get(coupon_id) if coupon_id else None
            if coupon and (not coupon.is_valid()
                           or float(cart.total()) < float(coupon.min_amount)):
                coupon = None

            # Shipping details: a saved address, or typed in on the form.
            address_id = form_value('address_id', cast=int)
            saved = Address.query.get(address_id) if address_id else None
            if saved and saved.user_id != current_user.user_id:
                saved = None
            if saved:
                recipient = saved.recipient_name
                line      = ', '.join(p for p in [saved.line1, saved.line2] if p)
                city, postal, country, phone = (saved.city, saved.postal_code,
                                                saved.country, saved.phone)
            else:
                recipient = (form_value('recipient_name', current_user.name) or '').strip()
                line      = (form_value('address', '') or '').strip()
                city      = (form_value('city', '') or '').strip()
                postal    = (form_value('postal_code', '') or '').strip() or None
                country   = (form_value('country', 'Cambodia') or 'Cambodia').strip()
                phone     = (form_value('phone', '') or '').strip()

            if not line or not city or not phone:
                if wants_json():
                    return api_error('Please fill in all shipping details.', 422)
                flash('Please fill in all shipping details.', 'danger')
                return render_checkout(coupon, method, coupon_code)

            # Re-check stock at the last moment — the cart may be hours old.
            for item in cart.items:
                if item.quantity > item.variant.stock:
                    msg = (f'"{item.variant.product.name}" only has '
                           f'{item.variant.stock} left. Please update your cart.')
                    if wants_json():
                        return api_error(msg, 409)
                    flash(msg, 'warning')
                    return redirect(url_for('cart.view_cart'))

            quote = _quote(cart, coupon, method)

            order = Order(
                user_id      = current_user.user_id,
                coupon_id    = coupon.coupon_id if coupon else None,
                shipping_method_id = method.method_id if method else None,
                subtotal        = quote['subtotal'],
                discount_amount = quote['discount'],
                shipping_fee    = quote['shipping_fee'],
                tax             = quote['tax'],
                total_amount    = quote['total'],
                status       = 'Pending'
            )
            db.session.add(order)
            db.session.flush()

            db.session.add(OrderStatusHistory(
                order_id=order.order_id, from_status=None, to_status='Pending',
                note='Order placed by customer', changed_by_user_id=current_user.user_id))

            for item in cart.items:
                db.session.add(OrderItem(
                    order_id      = order.order_id,
                    variant_id    = item.variant_id,
                    quantity      = item.quantity,
                    price         = item.variant.price,
                    product_name  = item.variant.product.name,
                    variant_label = item.variant.label(),
                ))
                item.variant.stock -= item.quantity
                db.session.add(InventoryLog(
                    variant_id  = item.variant_id,
                    change_type = 'OUT',
                    quantity    = item.quantity,
                    reference   = f'order_{order.order_id}'
                ))

            db.session.add(Payment(
                order_id = order.order_id,
                method   = payment_method,
                amount   = quote['total'],
                status   = 'Pending'
            ))

            db.session.add(Shipping(
                order_id       = order.order_id,
                recipient_name = recipient,
                address        = line,
                city           = city,
                postal_code    = postal,
                country        = country,
                phone          = phone,
                status         = 'Preparing'
            ))

            for item in cart.items.all():
                db.session.delete(item)

            db.session.commit()
            db.session.add(Notification(
                user_id=current_user.user_id,
                title='Order placed',
                message=f'Your order #{order.order_id} has been placed successfully.',
                kind='order',
            ))
            db.session.commit()
            flash(f'Order #{order.order_id} placed successfully!', 'success')

            # ── KHQR payment ───────────────────────────────────────────────────
            if payment_method == 'KHQR':
                merchant = BakongMerchant.query.filter_by(is_active=True).first()
                if not merchant:
                    if wants_json():
                        return api_error('KHQR payment not available. No active merchant configured.',
                                         422, order=order.to_dict())
                    flash('KHQR payment not available. No active merchant configured.', 'danger')
                    return redirect(url_for('orders.detail', order_id=order.order_id))

                khqr = KHQR(current_app.config.get('BAKONG_TOKEN'))
                qr_string = khqr.create_qr(
                    merchant_name=merchant.merchant_name,
                    merchant_city=merchant.merchant_city,
                    amount=quote['total'],
                    currency='USD',
                    store_label=current_app.config.get('STORE_NAME', 'Skincare Store'),
                    terminal_label=merchant.terminal_label,
                    phone_number='061275099',
                    bill_number=str(order.order_id),
                    bank_account=merchant.bank_account
                )
                md5_hash = khqr.generate_md5(qr_string)

                tx = PaymentTransaction(
                    qr_string=qr_string,
                    md5_hash=md5_hash,
                    amount=quote['total'],
                    currency='USD',
                    user_id=current_user.user_id,
                    order_id=order.order_id
                )
                db.session.add(tx)
                db.session.commit()
                if wants_json():
                    return api_ok({'order': order.to_dict(), 'transaction': tx.to_dict()},
                                  status=201)
                return redirect(url_for('orders.khqr_payment', tx_id=tx.transaction_id))

            if wants_json():
                return api_ok(order.to_dict(), status=201)
            return redirect(url_for('orders.detail', order_id=order.order_id))

    if wants_json():
        return api_ok({
            'cart': cart.to_dict(),
            'coupon_code': '',
            'addresses': [a.to_dict() for a in addresses],
            'shipping_methods': [m.to_dict(subtotal=cart.total()) for m in methods],
            **_quote(cart, None, default_method),
        })
    return render_checkout(None, default_method)


@orders_bp.route('/khqr-payment/<int:tx_id>')
@login_required
def khqr_payment(tx_id):
    tx = PaymentTransaction.query.get_or_404(tx_id)
    if tx.user_id != current_user.user_id and not current_user.is_admin():
        if wants_json():
            return api_error('Not authorised.', 403)
        flash('Not authorised.', 'danger')
        return redirect(url_for('orders.my_orders'))

    if tx.status != 'Pending':
        if wants_json():
            return api_error('Payment already processed.', 409, transaction=tx.to_dict())
        flash('Payment already processed.', 'info')
        return redirect(url_for('orders.detail', order_id=tx.order_id))

    # Generate QR image
    import qrcode
    import io
    import base64

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(tx.qr_string)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    qr_b64 = base64.b64encode(buffer.getvalue()).decode()

    # Generate deeplink
    khqr = KHQR(current_app.config.get('BAKONG_TOKEN'))
    deeplink = khqr.generate_deeplink(tx.qr_string)

    if wants_json():
        return api_ok({'transaction': tx.to_dict(), 'qr_base64': qr_b64, 'deeplink': deeplink})

    return render_template('orders/khqr_payment.html', tx=tx, qr_b64=qr_b64, deeplink=deeplink)


@orders_bp.route('/api/check-payment', methods=['POST'])
@login_required
def api_check_payment():
    data = request.get_json()
    md5 = data.get('md5')
    if not md5:
        return {'error': 'MD5 hash required'}, 400

    # Find the transaction
    tx = PaymentTransaction.query.filter_by(md5_hash=md5).first()
    if not tx:
        return {'error': 'Transaction not found'}, 404

    if tx.user_id != current_user.user_id and not current_user.is_admin():
        return {'error': 'Not authorised'}, 403

    # Call Bakong API
    bakong_token = current_app.config.get('BAKONG_TOKEN')
    if not bakong_token:
        return {'error': 'Bakong token not configured'}, 500

    url = 'https://api-bakong.nbc.gov.kh/v1/check_transaction_by_md5'
    headers = {
        'Authorization': f'Bearer {bakong_token}',
        'Content-Type': 'application/json'
    }
    payload = {'md5': md5}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        result = response.json()

        if response.status_code == 200 and result.get('responseCode') == 0:
            # Payment successful
            tx.status = 'Paid'
            tx.paid_at = datetime.utcnow()
            tx.order.payment.status = 'Paid'
            tx.order.payment.paid_at = datetime.utcnow()
            tx.order.set_status('Processing', note='Payment received via KHQR',
                                changed_by=tx.user_id)
            db.session.commit()
            return {'status': 'paid', 'message': 'Payment successful!'}
        else:
            return {'status': 'pending', 'message': 'Payment pending.'}
    except Exception as e:
        return {'error': f'API call failed: {str(e)}'}, 500
