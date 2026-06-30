from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from datetime import datetime
from app.models import (db, Cart, CartItem, Order, OrderItem,
                        Payment, Shipping, Coupon, InventoryLog,
                        PaymentTransaction, BakongMerchant)
import hashlib
from bakong_khqr import KHQR
import requests

orders_bp = Blueprint('orders', __name__)


@orders_bp.route('/')
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=current_user.user_id)\
                  .order_by(Order.created_at.desc()).all()
    return render_template('orders/list.html', orders=orders)


@orders_bp.route('/<int:order_id>')
@login_required
def detail(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.user_id and not current_user.is_admin():
        flash('Not authorised.', 'danger')
        return redirect(url_for('orders.my_orders'))
    return render_template('orders/detail.html', order=order)


@orders_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart = Cart.query.filter_by(user_id=current_user.user_id).first()
    if not cart or cart.items.count() == 0:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('cart.view_cart'))

    coupon      = None
    coupon_code = ''
    total       = cart.total()
    discount    = 0

    if request.method == 'POST':
        action = request.form.get('action')

        # Apply coupon
        if action == 'apply_coupon':
            coupon_code = request.form.get('coupon_code', '').strip().upper()
            coupon = Coupon.query.filter_by(code=coupon_code).first()
            if not coupon or not coupon.is_valid():
                flash('Invalid or expired coupon.', 'danger')
                coupon = None
            elif float(total) < float(coupon.min_amount):
                flash(f'Minimum order amount for this coupon is ${coupon.min_amount}.', 'warning')
                coupon = None
            else:
                discounted = coupon.apply(total)
                discount   = total - discounted
                total      = discounted
                flash(f'Coupon applied! You saved ${discount:.2f}.', 'success')
            return render_template('orders/checkout.html', cart=cart, coupon=coupon,
                                   total=total, discount=discount, coupon_code=coupon_code)

        # Place order
        if action == 'place_order':
            address    = request.form.get('address', '').strip()
            city       = request.form.get('city', '').strip()
            phone      = request.form.get('phone', '').strip()
            method     = request.form.get('payment_method', 'Cash')
            coupon_id  = request.form.get('coupon_id', type=int)
            final_total = request.form.get('final_total', type=float) or cart.total()

            if not address or not city or not phone:
                flash('Please fill in all shipping details.', 'danger')
                return render_template('orders/checkout.html', cart=cart, coupon=coupon,
                                       total=total, discount=discount)

            # Create Order
            coupon_obj = Coupon.query.get(coupon_id) if coupon_id else None
            order = Order(
                user_id      = current_user.user_id,
                coupon_id    = coupon_id,
                total_amount = final_total,
                status       = 'Pending'
            )
            db.session.add(order)
            db.session.flush()

            # Create Order Items & reduce stock
            for item in cart.items:
                oi = OrderItem(
                    order_id   = order.order_id,
                    variant_id = item.variant_id,
                    quantity   = item.quantity,
                    price      = item.variant.price
                )
                db.session.add(oi)
                item.variant.stock -= item.quantity
                log = InventoryLog(
                    variant_id  = item.variant_id,
                    change_type = 'OUT',
                    quantity    = item.quantity,
                    reference   = f'order_{order.order_id}'
                )
                db.session.add(log)

            # Payment
            payment = Payment(
                order_id = order.order_id,
                method   = method,
                amount   = final_total,
                status   = 'Pending'
            )
            db.session.add(payment)

            # Shipping
            shipping = Shipping(
                order_id = order.order_id,
                address  = address,
                city     = city,
                phone    = phone,
                status   = 'Preparing'
            )
            db.session.add(shipping)

            # Clear cart
            for item in cart.items.all():
                db.session.delete(item)

            db.session.commit()
            flash(f'Order #{order.order_id} placed successfully!', 'success')

            # Handle KHQR payment
            if method == 'KHQR':
                merchant = BakongMerchant.query.filter_by(is_active=True).first()
                if not merchant:
                    flash('KHQR payment not available. No active merchant configured.', 'danger')
                    return redirect(url_for('orders.detail', order_id=order.order_id))

                khqr = KHQR(current_app.config.get('BAKONG_TOKEN'))
                qr_string = khqr.create_qr(
                    merchant_name=merchant.merchant_name,
                    merchant_city=merchant.merchant_city,
                    amount=final_total,
                    currency='USD',
                    store_label='Ecommerce',
                    terminal_label=merchant.terminal_label,
                    phone_number='061275099',
                    bill_number=str(order.order_id),
                    bank_account=merchant.bank_account
                )
                md5_hash = khqr.generate_md5(qr_string)

                tx = PaymentTransaction(
                    qr_string=qr_string,
                    md5_hash=md5_hash,
                    amount=final_total,
                    currency='USD',
                    user_id=current_user.user_id,
                    order_id=order.order_id
                )
                db.session.add(tx)
                db.session.commit()
                return redirect(url_for('orders.khqr_payment', tx_id=tx.transaction_id))

            return redirect(url_for('orders.detail', order_id=order.order_id))

    return render_template('orders/checkout.html', cart=cart, coupon=coupon,
                           total=total, discount=0, coupon_code='')


@orders_bp.route('/khqr-payment/<int:tx_id>')
@login_required
def khqr_payment(tx_id):
    tx = PaymentTransaction.query.get_or_404(tx_id)
    if tx.user_id != current_user.user_id and not current_user.is_admin():
        flash('Not authorised.', 'danger')
        return redirect(url_for('orders.my_orders'))

    if tx.status != 'Pending':
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
            db.session.commit()
            return {'status': 'paid', 'message': 'Payment successful!'}
        else:
            return {'status': 'pending', 'message': 'Payment pending.'}
    except Exception as e:
        return {'error': f'API call failed: {str(e)}'}, 500
