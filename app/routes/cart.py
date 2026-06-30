from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.models import db, Cart, CartItem, ProductVariant

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
    return render_template('cart/cart.html', cart=cart)


@cart_bp.route('/add', methods=['POST'])
@login_required
def add_to_cart():
    variant_id = request.form.get('variant_id', type=int)
    quantity   = request.form.get('quantity', 1, type=int)

    variant = ProductVariant.query.get_or_404(variant_id)
    if quantity < 1:
        quantity = 1
    if quantity > variant.stock:
        flash(f'Only {variant.stock} in stock.', 'warning')
        quantity = variant.stock

    cart = get_or_create_cart()
    item = CartItem.query.filter_by(cart_id=cart.cart_id, variant_id=variant_id).first()

    if item:
        new_qty = item.quantity + quantity
        if new_qty > variant.stock:
            new_qty = variant.stock
            flash('Max stock reached.', 'warning')
        item.quantity = new_qty
    else:
        item = CartItem(cart_id=cart.cart_id, variant_id=variant_id, quantity=quantity)
        db.session.add(item)

    db.session.commit()
    flash(f'"{variant.product.name}" added to cart.', 'success')
    return redirect(request.referrer or url_for('cart.view_cart'))


@cart_bp.route('/update/<int:item_id>', methods=['POST'])
@login_required
def update_item(item_id):
    item     = CartItem.query.get_or_404(item_id)
    quantity = request.form.get('quantity', 1, type=int)

    if item.cart.user_id != current_user.user_id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('cart.view_cart'))

    if quantity < 1:
        db.session.delete(item)
    elif quantity > item.variant.stock:
        item.quantity = item.variant.stock
        flash('Quantity adjusted to available stock.', 'warning')
    else:
        item.quantity = quantity

    db.session.commit()
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/remove/<int:item_id>', methods=['POST'])
@login_required
def remove_item(item_id):
    item = CartItem.query.get_or_404(item_id)
    if item.cart.user_id != current_user.user_id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('cart.view_cart'))
    db.session.delete(item)
    db.session.commit()
    flash('Item removed.', 'info')
    return redirect(url_for('cart.view_cart'))


@cart_bp.route('/clear', methods=['POST'])
@login_required
def clear_cart():
    cart = get_or_create_cart()
    for item in cart.items:
        db.session.delete(item)
    db.session.commit()
    flash('Cart cleared.', 'info')
    return redirect(url_for('cart.view_cart'))
