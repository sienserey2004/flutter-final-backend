from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.models import db, Product, ProductVariant, Category, Review

products_bp = Blueprint('products', __name__)


@products_bp.route('/')
def list_products():
    page        = request.args.get('page', 1, type=int)
    category_id = request.args.get('category', type=int)
    search      = request.args.get('q', '').strip()
    sort        = request.args.get('sort', 'newest')

    query = Product.query

    if category_id:
        query = query.filter_by(category_id=category_id)
    if search:
        query = query.filter(Product.name.ilike(f'%{search}%'))

    if sort == 'price_asc':
        query = query.order_by(Product.base_price.asc())
    elif sort == 'price_desc':
        query = query.order_by(Product.base_price.desc())
    else:
        query = query.order_by(Product.created_at.desc())

    products   = query.paginate(page=page, per_page=12, error_out=False)
    categories = Category.query.all()
    return render_template('products/list.html',
                           products=products,
                           categories=categories,
                           current_category=category_id,
                           search=search,
                           sort=sort)


@products_bp.route('/<int:product_id>')
def detail(product_id):
    product = Product.query.get_or_404(product_id)
    reviews = Review.query.filter_by(product_id=product_id).order_by(Review.created_at.desc()).all()
    related = Product.query.filter(
        Product.category_id == product.category_id,
        Product.product_id  != product_id
    ).limit(4).all()
    return render_template('products/detail.html',
                           product=product,
                           reviews=reviews,
                           related=related)
