from flask import Blueprint, render_template
from flask_login import current_user
from sqlalchemy import func
from app.models import (db, Product, ProductVariant, Category, Brand, Promotion,
                        SkinConcern, SkinType, Bundle, Review, Ingredient)
from app.api import wants_json, api_ok
from datetime import datetime

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    now = datetime.utcnow()

    new_in = (Product.query.filter_by(is_active=True)
              .order_by(Product.created_at.desc()).limit(8).all())

    # Best sellers by review volume — a decent stand-in until order stats exist.
    rated = (db.session.query(Review.product_id, func.count(Review.review_id).label('n'))
             .group_by(Review.product_id).subquery())
    bestsellers = (Product.query.join(rated, rated.c.product_id == Product.product_id)
                   .filter(Product.is_active.is_(True))
                   .order_by(rated.c.n.desc()).limit(8).all())
    if not bestsellers:
        bestsellers = new_in[:4]

    on_sale = (Product.query.filter(
                   Product.is_active.is_(True),
                   Product.variants.any(ProductVariant.compare_at_price > ProductVariant.price))
               .limit(8).all())

    top_categories = (Category.query.filter_by(parent_id=None)
                      .order_by(Category.sort_order).all())
    shelf_categories = (Category.query.filter(Category.parent_id.isnot(None))
                        .order_by(Category.sort_order).limit(8).all())

    active_promos = Promotion.query.filter(
        Promotion.start_date <= now,
        Promotion.end_date   >= now
    ).all()

    concerns = SkinConcern.query.order_by(SkinConcern.name).limit(8).all()
    skin_types = SkinType.query.order_by(SkinType.skin_type_id).all()
    brands = Brand.query.filter_by(is_active=True).order_by(Brand.name).all()
    bundles = Bundle.query.filter_by(is_active=True).order_by(Bundle.price).limit(3).all()

    # Headline figures for the hero strip — derived, never asserted. If a claim
    # isn't backed by a column we don't put a number on it.
    live_products = Product.query.filter_by(is_active=True).count()
    stats = {
        'products':      live_products,
        'actives':       Ingredient.query.filter_by(is_active_ingredient=True).count(),
        'brands':        Brand.query.filter_by(is_active=True).count(),
        'cruelty_free':  Product.query.filter_by(is_active=True, is_cruelty_free=True).count(),
        'inci_listed':   Product.query.filter(Product.is_active.is_(True),
                                              Product.ingredients_full.isnot(None)).count(),
    }
    stats['inci_pct'] = (round(stats['inci_listed'] / live_products * 100)
                         if live_products else 0)

    if wants_json():
        return api_ok({
            'new_in': [p.to_dict(include_variants=False) for p in new_in],
            'bestsellers': [p.to_dict(include_variants=False) for p in bestsellers],
            'on_sale': [p.to_dict(include_variants=False) for p in on_sale],
            'categories': [c.to_dict(include_children=True) for c in top_categories],
            'shelf_categories': [c.to_dict() for c in shelf_categories],
            'concerns': [c.to_dict() for c in concerns],
            'skin_types': [s.to_dict() for s in skin_types],
            'brands': [b.to_dict() for b in brands],
            'bundles': [b.to_dict() for b in bundles],
            'active_promos': [p.to_dict() for p in active_promos],
            'stats': stats,
        })

    return render_template('main/index.html',
                           stats=stats,
                           new_in=new_in,
                           bestsellers=bestsellers,
                           on_sale=on_sale,
                           categories=top_categories,
                           shelf_categories=shelf_categories,
                           concerns=concerns,
                           skin_types=skin_types,
                           brands=brands,
                           bundles=bundles,
                           active_promos=active_promos)


@main_bp.route('/ingredients')
def ingredient_glossary():
    """A plain-language reference for every active in the catalog — the page
    that turns 'what is niacinamide' searches into product views."""
    actives = Ingredient.query.filter_by(is_active_ingredient=True)\
                              .order_by(Ingredient.name).all()
    supporting = Ingredient.query.filter_by(is_active_ingredient=False)\
                                 .order_by(Ingredient.name).all()
    if wants_json():
        return api_ok({
            'actives': [i.to_dict() for i in actives],
            'supporting': [i.to_dict() for i in supporting],
        })
    return render_template('main/ingredients.html', actives=actives, supporting=supporting)
