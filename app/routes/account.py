"""Customer account area — skin profile, addresses, wishlist, subscriptions,
back-in-stock alerts and returns."""
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app.models import (db, Product, ProductVariant, SkinType, SkinConcern,
                        UserSkinProfile, Address, Wishlist, WishlistItem,
                        Order, OrderItem, ReturnRequest, ReturnItem,
                        BackInStockAlert, Subscription)
from app.api import wants_json, api_ok, api_error, form_value, form_list

account_bp = Blueprint('account', __name__)


# ── Helpers ────────────────────────────────────────────────────────────────────
def get_or_create_wishlist():
    wl = Wishlist.query.filter_by(user_id=current_user.user_id).first()
    if not wl:
        wl = Wishlist(user_id=current_user.user_id)
        db.session.add(wl)
        db.session.commit()
    return wl


def _bool(name):
    """Checkbox from an HTML form, or a real boolean from a JSON body."""
    if request.is_json:
        return bool((request.get_json(silent=True) or {}).get(name))
    return name in request.form


# ── Overview ───────────────────────────────────────────────────────────────────
@account_bp.route('/')
@login_required
def overview():
    wishlist = get_or_create_wishlist()
    orders = (Order.query.filter_by(user_id=current_user.user_id)
              .order_by(Order.created_at.desc()).limit(5).all())
    subs = Subscription.query.filter_by(user_id=current_user.user_id)\
                             .filter(Subscription.status != 'Cancelled').all()
    if wants_json():
        return api_ok({
            'user': current_user.to_dict(),
            'skin_profile': current_user.skin_profile.to_dict() if current_user.skin_profile else None,
            'addresses': [a.to_dict() for a in current_user.addresses],
            'wishlist_count': wishlist.item_count(),
            'recent_orders': [o.to_dict(include_items=False) for o in orders],
            'subscriptions': [s.to_dict() for s in subs],
        })
    return render_template('account/overview.html', wishlist=wishlist,
                           orders=orders, subscriptions=subs)


# ── Skin profile ───────────────────────────────────────────────────────────────
@account_bp.route('/skin-profile', methods=['GET', 'POST'])
@login_required
def skin_profile():
    profile = current_user.skin_profile
    skin_types = SkinType.query.order_by(SkinType.skin_type_id).all()
    concerns = SkinConcern.query.order_by(SkinConcern.name).all()

    if request.method == 'POST':
        if not profile:
            profile = UserSkinProfile(user_id=current_user.user_id)
            db.session.add(profile)

        profile.skin_type_id = form_value('skin_type_id', cast=int)
        profile.age_range    = (form_value('age_range', '') or '').strip() or None
        profile.skin_tone    = (form_value('skin_tone', '') or '').strip() or None
        profile.is_sensitive = _bool('is_sensitive')
        profile.allergies    = (form_value('allergies', '') or '').strip() or None
        profile.notes        = (form_value('notes', '') or '').strip() or None
        db.session.flush()

        chosen = set(form_list('concern_ids', cast=int))
        current = {c.concern_id: c for c in profile.concerns}
        for cid in chosen - set(current):
            concern = SkinConcern.query.get(cid)
            if concern:
                profile.concerns.append(concern)
        for cid in set(current) - chosen:
            profile.concerns.remove(current[cid])

        db.session.commit()
        flash('Skin profile saved — your recommendations are updated.', 'success')
        if wants_json():
            return api_ok(profile.to_dict())
        return redirect(url_for('products.for_you'))

    if wants_json():
        return api_ok({
            'profile': profile.to_dict() if profile else None,
            'skin_types': [s.to_dict() for s in skin_types],
            'concerns': [c.to_dict() for c in concerns],
            'age_ranges': UserSkinProfile.AGE_RANGES,
            'skin_tones': UserSkinProfile.SKIN_TONES,
        })
    return render_template('account/skin_profile.html', profile=profile,
                           skin_types=skin_types, concerns=concerns,
                           age_ranges=UserSkinProfile.AGE_RANGES,
                           skin_tones=UserSkinProfile.SKIN_TONES)


# ── Addresses ──────────────────────────────────────────────────────────────────
@account_bp.route('/addresses')
@login_required
def addresses():
    items = current_user.addresses.order_by(Address.is_default.desc(),
                                            Address.created_at.desc()).all()
    if wants_json():
        return api_ok([a.to_dict() for a in items])
    return render_template('account/addresses.html', addresses=items)


def _save_address(address):
    address.label          = (form_value('label', 'Home') or 'Home').strip()
    address.recipient_name = (form_value('recipient_name', '') or '').strip()
    address.phone          = (form_value('phone', '') or '').strip()
    address.line1          = (form_value('line1', '') or '').strip()
    address.line2          = (form_value('line2', '') or '').strip() or None
    address.city           = (form_value('city', '') or '').strip()
    address.state          = (form_value('state', '') or '').strip() or None
    address.postal_code    = (form_value('postal_code', '') or '').strip() or None
    address.country        = (form_value('country', 'Cambodia') or 'Cambodia').strip()
    missing = not all([address.recipient_name, address.phone, address.line1, address.city])
    return missing


def _set_default(address):
    """Only one default per user."""
    current_user.addresses.filter(Address.address_id != address.address_id)\
                          .update({'is_default': False})
    address.is_default = True


@account_bp.route('/addresses/new', methods=['GET', 'POST'])
@login_required
def new_address():
    if request.method == 'POST':
        address = Address(user_id=current_user.user_id)
        if _save_address(address):
            if wants_json():
                return api_error('Recipient, phone, address line 1 and city are required.', 422)
            flash('Recipient, phone, address line 1 and city are required.', 'danger')
            return render_template('account/address_form.html', address=None)
        db.session.add(address)
        db.session.flush()
        if _bool('is_default') or current_user.addresses.count() == 1:
            _set_default(address)
        db.session.commit()
        flash('Address saved.', 'success')
        if wants_json():
            return api_ok(address.to_dict(), status=201)
        return redirect(url_for('account.addresses'))
    if wants_json():
        return api_error('POST recipient_name/phone/line1/city to create an address.', 405)
    return render_template('account/address_form.html', address=None)


@account_bp.route('/addresses/<int:address_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_address(address_id):
    address = Address.query.get_or_404(address_id)
    if address.user_id != current_user.user_id:
        abort(403)
    if request.method == 'POST':
        if _save_address(address):
            if wants_json():
                return api_error('Recipient, phone, address line 1 and city are required.', 422)
            flash('Recipient, phone, address line 1 and city are required.', 'danger')
            return render_template('account/address_form.html', address=address)
        if _bool('is_default'):
            _set_default(address)
        db.session.commit()
        flash('Address updated.', 'success')
        if wants_json():
            return api_ok(address.to_dict())
        return redirect(url_for('account.addresses'))
    if wants_json():
        return api_ok(address.to_dict())
    return render_template('account/address_form.html', address=address)


@account_bp.route('/addresses/<int:address_id>/default', methods=['POST'])
@login_required
def make_default_address(address_id):
    address = Address.query.get_or_404(address_id)
    if address.user_id != current_user.user_id:
        abort(403)
    _set_default(address)
    db.session.commit()
    flash('Default address updated.', 'success')
    if wants_json():
        return api_ok(address.to_dict())
    return redirect(url_for('account.addresses'))


@account_bp.route('/addresses/<int:address_id>/delete', methods=['POST'])
@login_required
def delete_address(address_id):
    address = Address.query.get_or_404(address_id)
    if address.user_id != current_user.user_id:
        abort(403)
    db.session.delete(address)
    db.session.commit()
    flash('Address removed.', 'info')
    if wants_json():
        return api_ok(message='Address removed.')
    return redirect(url_for('account.addresses'))


# ── Wishlist ───────────────────────────────────────────────────────────────────
@account_bp.route('/wishlist')
@login_required
def wishlist():
    wl = get_or_create_wishlist()
    if wants_json():
        return api_ok(wl.to_dict())
    return render_template('account/wishlist.html', wishlist=wl)


@account_bp.route('/wishlist/toggle', methods=['POST'])
@login_required
def toggle_wishlist():
    product_id = form_value('product_id', cast=int)
    product = Product.query.get_or_404(product_id)
    wl = get_or_create_wishlist()

    existing = wl.items.filter_by(product_id=product_id).first()
    if existing:
        db.session.delete(existing)
        added = False
        flash(f'Removed "{product.name}" from your wishlist.', 'info')
    else:
        db.session.add(WishlistItem(wishlist_id=wl.wishlist_id, product_id=product_id))
        added = True
        flash(f'Saved "{product.name}" to your wishlist.', 'success')
    db.session.commit()

    if wants_json():
        return api_ok({'in_wishlist': added, 'wishlist_count': wl.item_count()})
    return redirect(request.referrer or url_for('account.wishlist'))


# ── Back-in-stock alerts ───────────────────────────────────────────────────────
@account_bp.route('/alerts')
@login_required
def alerts():
    items = BackInStockAlert.query.filter_by(user_id=current_user.user_id)\
                                  .order_by(BackInStockAlert.created_at.desc()).all()
    if wants_json():
        return api_ok([a.to_dict() for a in items])
    return render_template('account/alerts.html', alerts=items)


@account_bp.route('/alerts/subscribe', methods=['POST'])
@login_required
def subscribe_alert():
    variant_id = form_value('variant_id', cast=int)
    variant = ProductVariant.query.get_or_404(variant_id)
    email = (form_value('email', current_user.email) or current_user.email).strip()

    existing = BackInStockAlert.query.filter_by(variant_id=variant_id, email=email).first()
    if existing:
        if wants_json():
            return api_ok(existing.to_dict(), message='Already on the list.')
        flash("You're already on the list for this one.", 'info')
        return redirect(request.referrer or url_for('account.alerts'))

    alert = BackInStockAlert(variant_id=variant_id, user_id=current_user.user_id, email=email)
    db.session.add(alert)
    db.session.commit()
    flash(f'We\'ll email you when "{variant.product.name}" is back.', 'success')
    if wants_json():
        return api_ok(alert.to_dict(), status=201)
    return redirect(request.referrer or url_for('account.alerts'))


@account_bp.route('/alerts/<int:alert_id>/delete', methods=['POST'])
@login_required
def delete_alert(alert_id):
    alert = BackInStockAlert.query.get_or_404(alert_id)
    if alert.user_id != current_user.user_id:
        abort(403)
    db.session.delete(alert)
    db.session.commit()
    flash('Alert removed.', 'info')
    if wants_json():
        return api_ok(message='Alert removed.')
    return redirect(url_for('account.alerts'))


# ── Subscriptions (replenishment) ──────────────────────────────────────────────
@account_bp.route('/subscriptions')
@login_required
def subscriptions():
    items = Subscription.query.filter_by(user_id=current_user.user_id)\
                              .order_by(Subscription.created_at.desc()).all()
    if wants_json():
        return api_ok([s.to_dict() for s in items])
    return render_template('account/subscriptions.html', subscriptions=items,
                           intervals=Subscription.INTERVALS)


@account_bp.route('/subscriptions/new', methods=['POST'])
@login_required
def new_subscription():
    variant_id    = form_value('variant_id', cast=int)
    quantity      = max(1, form_value('quantity', 1, cast=int) or 1)
    interval_days = form_value('interval_days', 30, cast=int) or 30
    variant = ProductVariant.query.get_or_404(variant_id)

    sub = Subscription(
        user_id=current_user.user_id,
        variant_id=variant_id,
        address_id=(current_user.default_address().address_id
                    if current_user.default_address() else None),
        quantity=quantity,
        interval_days=interval_days,
        discount_percent=10,
        next_delivery_at=datetime.utcnow() + timedelta(days=interval_days),
    )
    db.session.add(sub)
    db.session.commit()
    flash(f'Subscribed to "{variant.product.name}" — 10% off every refill.', 'success')
    if wants_json():
        return api_ok(sub.to_dict(), status=201)
    return redirect(url_for('account.subscriptions'))


@account_bp.route('/subscriptions/<int:sub_id>/<action>', methods=['POST'])
@login_required
def update_subscription(sub_id, action):
    sub = Subscription.query.get_or_404(sub_id)
    if sub.user_id != current_user.user_id:
        abort(403)
    if action == 'pause':
        sub.status = 'Paused'
        flash('Subscription paused.', 'info')
    elif action == 'resume':
        sub.status = 'Active'
        sub.next_delivery_at = datetime.utcnow() + timedelta(days=sub.interval_days)
        flash('Subscription resumed.', 'success')
    elif action == 'cancel':
        sub.status = 'Cancelled'
        sub.cancelled_at = datetime.utcnow()
        flash('Subscription cancelled.', 'info')
    else:
        if wants_json():
            return api_error('Unknown action.', 422)
        abort(404)
    db.session.commit()
    if wants_json():
        return api_ok(sub.to_dict())
    return redirect(url_for('account.subscriptions'))


# ── Returns ────────────────────────────────────────────────────────────────────
@account_bp.route('/returns')
@login_required
def returns():
    items = ReturnRequest.query.filter_by(user_id=current_user.user_id)\
                               .order_by(ReturnRequest.created_at.desc()).all()
    if wants_json():
        return api_ok([r.to_dict() for r in items])
    return render_template('account/returns.html', returns=items)


@account_bp.route('/returns/new/<int:order_id>', methods=['GET', 'POST'])
@login_required
def new_return(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.user_id:
        abort(403)
    if order.status not in ('Shipped', 'Delivered'):
        if wants_json():
            return api_error('You can only return an order once it has shipped.', 422)
        flash('You can only return an order once it has shipped.', 'warning')
        return redirect(url_for('orders.detail', order_id=order_id))

    if request.method == 'POST':
        reason  = (form_value('reason', '') or '').strip()
        details = (form_value('details', '') or '').strip()
        item_ids = set(form_list('order_item_ids', cast=int))
        if not reason or not item_ids:
            if wants_json():
                return api_error('Pick at least one item and a reason.', 422)
            flash('Pick at least one item and a reason.', 'danger')
            return render_template('account/return_form.html', order=order,
                                   reasons=ReturnRequest.REASONS)

        req = ReturnRequest(order_id=order_id, user_id=current_user.user_id,
                            reason=reason, details=details, status='Requested')
        db.session.add(req)
        db.session.flush()

        refund = 0.0
        for item in order.items:
            if item.order_item_id not in item_ids:
                continue
            qty = form_value(f'quantity_{item.order_item_id}', item.quantity, cast=int)
            qty = max(1, min(qty or 1, item.quantity - item.returned_quantity()))
            db.session.add(ReturnItem(return_id=req.return_id,
                                      order_item_id=item.order_item_id, quantity=qty))
            refund += float(item.price) * qty
        req.refund_amount = round(refund, 2)

        db.session.commit()
        flash(f'Return #{req.return_id} submitted. We\'ll review it within 2 business days.',
              'success')
        if wants_json():
            return api_ok(req.to_dict(), status=201)
        return redirect(url_for('account.returns'))

    if wants_json():
        return api_ok({'order': order.to_dict(), 'reasons': ReturnRequest.REASONS})
    return render_template('account/return_form.html', order=order,
                           reasons=ReturnRequest.REASONS)


@account_bp.route('/returns/<int:return_id>')
@login_required
def return_detail(return_id):
    req = ReturnRequest.query.get_or_404(return_id)
    if req.user_id != current_user.user_id and not current_user.is_admin():
        abort(403)
    if wants_json():
        return api_ok(req.to_dict())
    return render_template('account/return_detail.html', req=req)
