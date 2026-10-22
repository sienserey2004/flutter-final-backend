"""Standalone category browsing.

Categories are also embedded in the homepage and product-list payloads, but a
mobile category screen shouldn't have to fetch a whole product page to get
them — these endpoints serve the taxonomy on its own.

Mounted twice by the app factory: /categories (HTML) and /api/categories (JSON).
"""
from flask import Blueprint, render_template, redirect, url_for, request, abort
from sqlalchemy import func
from app.models import db, Category, Product
from app.api import wants_json, api_ok

categories_bp = Blueprint('categories', __name__)

PER_PAGE = 12


def _live_counts():
    """{category_id: number of active products filed directly under it}.

    One grouped query instead of a COUNT per category — the tree endpoint would
    otherwise fire a query per node.
    """
    rows = (db.session.query(Product.category_id, func.count(Product.product_id))
            .filter(Product.is_active.is_(True))
            .group_by(Product.category_id).all())
    return {cid: n for cid, n in rows if cid is not None}


def _serialize(category, counts, depth=1):
    """A category plus its subtree, with both direct and roll-up product counts.

    `product_count` is what's filed on this category alone; `total_product_count`
    includes everything under its children, which is what a parent category
    ('Face') actually shows when tapped.
    """
    data = category.to_dict()
    data['product_count'] = counts.get(category.category_id, 0)
    data['total_product_count'] = sum(counts.get(cid, 0)
                                      for cid in category.descendant_ids())
    if depth > 0:
        children = sorted(category.children, key=lambda c: (c.sort_order, c.name))
        data['children'] = [_serialize(c, counts, depth - 1) for c in children]
    return data


def _find(identifier):
    """Look a category up by numeric id or by slug — mobile clients hold ids,
    web links carry slugs."""
    if isinstance(identifier, int) or str(identifier).isdigit():
        return Category.query.get(int(identifier))
    return Category.query.filter_by(slug=str(identifier)).first()


@categories_bp.route('/')
def list_categories():
    """The whole category tree. ?flat=1 returns one ungrouped list instead."""
    counts = _live_counts()
    flat = request.args.get('flat') == '1'

    if flat:
        items = Category.query.order_by(Category.sort_order, Category.name).all()
        payload = [_serialize(c, counts, depth=0) for c in items]
    else:
        roots = (Category.query.filter_by(parent_id=None)
                 .order_by(Category.sort_order, Category.name).all())
        # depth=2 covers root → child → grandchild, the deepest the catalog goes.
        payload = [_serialize(c, counts, depth=2) for c in roots]

    if wants_json():
        return api_ok(payload, count=len(payload))

    roots = (Category.query.filter_by(parent_id=None)
             .order_by(Category.sort_order, Category.name).all())
    # Roll-up totals precomputed here — the template can't walk the tree itself.
    totals = {r.category_id: sum(counts.get(cid, 0) for cid in r.descendant_ids())
              for r in roots}
    return render_template('products/categories.html',
                           roots=roots, counts=counts, totals=totals)


@categories_bp.route('/<identifier>')
def detail(identifier):
    """One category, its ancestry, its children, and a page of its products."""
    category = _find(identifier)
    if not category:
        abort(404)

    if not wants_json():
        # The HTML catalogue already renders this view, filters and all.
        return redirect(url_for('products.list_products', category=category.category_id))

    page = request.args.get('page', 1, type=int)
    products = (Product.query
                .filter(Product.is_active.is_(True),
                        Product.category_id.in_(category.descendant_ids()))
                .order_by(Product.created_at.desc())
                .paginate(page=page, per_page=PER_PAGE, error_out=False))

    counts = _live_counts()
    return api_ok({
        'category': _serialize(category, counts, depth=1),
        'breadcrumb': [c.to_dict() for c in category.breadcrumb()],
        'products': [p.to_dict(include_variants=False) for p in products.items],
        'page': products.page,
        'pages': products.pages,
        'total': products.total,
    })


@categories_bp.route('/<identifier>/products')
def products(identifier):
    """Just the products, for a client that already has the category."""
    category = _find(identifier)
    if not category:
        abort(404)

    if not wants_json():
        return redirect(url_for('products.list_products', category=category.category_id))

    page = request.args.get('page', 1, type=int)
    listing = (Product.query
               .filter(Product.is_active.is_(True),
                       Product.category_id.in_(category.descendant_ids()))
               .order_by(Product.created_at.desc())
               .paginate(page=page, per_page=PER_PAGE, error_out=False))

    return api_ok({
        'category_id': category.category_id,
        'products': [p.to_dict(include_variants=False) for p in listing.items],
        'page': listing.page,
        'pages': listing.pages,
        'total': listing.total,
    })
