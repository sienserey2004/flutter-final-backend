from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.models import db, Cart, CartItem, ProductVariant, Bundle
from app.api import wants_json, api_ok, api_error, form_value

cart_bp = Blueprint('cart', __name__)


def get_or_create_cart():
    cart = Cart.query.filter_by(user_id=current_user.user_id).first()
    if not cart:
        cart = Cart(user_id=current_user.user_id)
        db.session.add(cart)
        db.session.commit()
    return cart


@cart_bp.route('/')
@login_required
def view_cart():
    cart = get_or_create_cart()
    if wants_json():
        return api_ok(cart.to_dict())
    return render_template('cart/cart.html', cart=cart)


@cart_bp.route('/add', methods=['POST'])
@login_required
def add_to_cart():
    variant_id = form_value('variant_id', cast=int)
    quantity   = form_value('quantity', 1, cast=int)

    variant = ProductVariant.query.get_or_404(variant_id)
    warning = None
    if quantity < 1:
        quantity = 1
    if quantity > variant.stock:
        warning = f'Only {variant.stock} in stock.'
        flash(warning, 'warning')
        quantity = variant.stock

    cart = get_or_create_cart()
    item = CartItem.query.filter_by(cart_id=cart.cart_id, variant_id=variant_id).first()

    if item:
        new_qty = item.quantity + quantity
        if new_qty > variant.stock:
            new_qty = variant.stock
            warning = 'Max stock reached.'
            flash(warning, 'warning')
        item.quantity = new_qty
    else:
        item = CartItem(cart_id=cart.cart_id, variant_id=variant_id, quantity=quantity)
        db.session.add(item)

    db.session.commit()
    flash(f'"{variant.product.name}" added to cart.', 'success')

    if wants_json():
        return api_ok(cart.to_dict(), warning=warning)
    return redirect(request.referrer or url_for('cart.view_cart'))


@cart_bp.route('/add-bundle', methods=['POST'])
@login_required
def add_bundle():
    """Explode a routine kit into its individual variants so the customer can
    still adjust or drop a single product before checkout."""
    bundle_id = form_value('bundle_id', cast=int)
    bundle = Bundle.query.get_or_404(bundle_id)
    cart = get_or_create_cart()

    added, skipped = 0, []
    for member in bundle.items:
        variant = member.variant
        if variant.stock < member.quantity:
            skipped.append(variant.product.name)
            continue
        item = CartItem.query.filter_by(cart_id=cart.cart_id,
                                        variant_id=variant.variant_id).first()
        if item:
            item.quantity = min(item.quantity + member.quantity, variant.stock)
        else:
            db.session.add(CartItem(cart_id=cart.cart_id, variant_id=variant.variant_id,
                                    quantity=member.quantity))
        added += 1

    db.session.commit()

    warning = None
    if skipped:
        warning = 'Out of stock, not added: ' + ', '.join(skipped)
        flash(warning, 'warning')
    if added:
        flash(f'Added {added} product(s) from "{bundle.name}" to your cart.', 'success')

    if wants_json():
        return api_ok(cart.to_dict(), warning=warning)
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/update/<int:item_id>', methods=['POST'])
@login_required
def update_item(item_id):
    item     = CartItem.query.get_or_404(item_id)
    quantity = form_value('quantity', 1, cast=int)

    if item.cart.user_id != current_user.user_id:
        if wants_json():
            return api_error('Not authorised.', 403)
        flash('Not authorised.', 'danger')
        return redirect(url_for('cart.view_cart'))

    warning = None
    if quantity < 1:
        db.session.delete(item)
    elif quantity > item.variant.stock:
        item.quantity = item.variant.stock
        warning = 'Quantity adjusted to available stock.'
        flash(warning, 'warning')
    else:
        item.quantity = quantity

    db.session.commit()

    if wants_json():
        return api_ok(item.cart.to_dict(), warning=warning)
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/remove/<int:item_id>', methods=['POST'])
@login_required
def remove_item(item_id):
    item = CartItem.query.get_or_404(item_id)
    if item.cart.user_id != current_user.user_id:
        if wants_json():
            return api_error('Not authorised.', 403)
        flash('Not authorised.', 'danger')
        return redirect(url_for('cart.view_cart'))
    cart = item.cart
    db.session.delete(item)
    db.session.commit()
    flash('Item removed.', 'info')
    if wants_json():
        return api_ok(cart.to_dict())
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/clear', methods=['POST'])
@login_required
def clear_cart():
    cart = get_or_create_cart()
    for item in cart.items:
        db.session.delete(item)
    db.session.commit()
    flash('Cart cleared.', 'info')
    if wants_json():
        return api_ok(cart.to_dict())
    return redirect(url_for('cart.view_cart'))
