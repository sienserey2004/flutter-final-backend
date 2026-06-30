from flask import Blueprint, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, Review, Order, OrderItem

reviews_bp = Blueprint('reviews', __name__)


@reviews_bp.route('/submit', methods=['POST'])
@login_required
def submit():
    product_id = request.form.get('product_id', type=int)
    rating     = request.form.get('rating', type=int)
    comment    = request.form.get('comment', '').strip()

    if not product_id or not rating or rating not in range(1, 6):
        flash('Invalid review data.', 'danger')
        return redirect(request.referrer or url_for('main.index'))

    # Check if already reviewed
    existing = Review.query.filter_by(
        user_id=current_user.user_id, product_id=product_id
    ).first()
    if existing:
        existing.rating  = rating
        existing.comment = comment
        flash('Review updated.', 'success')
    else:
        review = Review(
            user_id    = current_user.user_id,
            product_id = product_id,
            rating     = rating,
            comment    = comment
        )
        db.session.add(review)
        flash('Review submitted.', 'success')

    db.session.commit()
    return redirect(url_for('products.detail', product_id=product_id))
