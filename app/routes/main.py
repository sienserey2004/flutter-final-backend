from flask import Blueprint, render_template
from app.models import Product, Category, Promotion
from datetime import datetime

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    featured = Product.query.order_by(Product.created_at.desc()).limit(8).all()
    categories = Category.query.all()
    now = datetime.utcnow()
    active_promos = Promotion.query.filter(
        Promotion.start_date <= now,
        Promotion.end_date   >= now
    ).all()
    return render_template('main/index.html',
                           featured=featured,
                           categories=categories,
                           active_promos=active_promos)
