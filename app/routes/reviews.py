from flask import Blueprint, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, Review, Order, OrderItem, ProductVariant, UserSkinProfile
from app.api import wants_json, api_ok, api_error, form_value

reviews_bp = Blueprint('reviews', __name__)


def _has_purchased(user_id, product_id):
    """True if this customer has a delivered/shipped order containing the product."""
    return db.session.query(OrderItem.order_item_id).join(Order).join(ProductVariant).filter(
        Order.user_id == user_id,
        Order.status.in_(['Shipped', 'Delivered']),
        ProductVariant.product_id == product_id,
    ).first() is not None


@reviews_bp.route('/submit', methods=['POST'])
@login_required
def submit():
    product_id = form_value('product_id', cast=int)
    rating     = form_value('rating', cast=int)
    title      = (form_value('title', '') or '').strip() or None
    comment    = (form_value('comment', '') or '').strip()

    if not product_id or not rating or rating not in range(1, 6):
        if wants_json():
            return api_error('Invalid review data.', 422)
        flash('Invalid review data.', 'danger')
        return redirect(request.referrer or url_for('main.index'))

    # Default the reviewer's skin context from their saved profile, but let the
    # form override it — people review products they bought for someone else.
    profile = current_user.skin_profile
    skin_type_id = form_value('skin_type_id', cast=int) or (
        profile.skin_type_id if profile else None)
    age_range = (form_value('age_range', '') or '').strip() or (
        profile.age_range if profile else None)

    existing = Review.query.filter_by(
        user_id=current_user.user_id, product_id=product_id
    ).first()
    if existing:
        existing.rating       = rating
        existing.title        = title
        existing.comment      = comment
        existing.skin_type_id = skin_type_id
        existing.age_range    = age_range
        flash('Review updated.', 'success')
        review = existing
    else:
        review = Review(
            user_id      = current_user.user_id,
            product_id   = product_id,
            rating       = rating,
            title        = title,
            comment      = comment,
            skin_type_id = skin_type_id,
            age_range    = age_range,
            is_verified_purchase = _has_purchased(current_user.user_id, product_id),
        )
        db.session.add(review)
        flash('Review submitted. Thank you!', 'success')

    db.session.commit()

    if wants_json():
        return api_ok(review.to_dict())
    return redirect(url_for('products.detail', product_id=product_id))


@reviews_bp.route('/<int:review_id>/delete', methods=['POST'])
@login_required
def delete(review_id):
    review = Review.query.get_or_404(review_id)
    if review.user_id != current_user.user_id and not current_user.is_admin():
        if wants_json():
            return api_error('Not authorised.', 403)
        flash('Not authorised.', 'danger')
        return redirect(request.referrer or url_for('main.index'))
    product_id = review.product_id
    db.session.delete(review)
    db.session.commit()
    flash('Review deleted.', 'info')
    if wants_json():
        return api_ok(message='Review deleted.')
    return redirect(url_for('products.detail', product_id=product_id))
