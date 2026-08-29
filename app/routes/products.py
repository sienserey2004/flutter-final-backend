from flask import Blueprint, render_template, request, abort
from flask_login import current_user
from sqlalchemy import or_, func
from app.models import (db, Product, ProductVariant, ProductIngredient, Category, Brand,
                        SkinType, SkinConcern, Ingredient, Review, Bundle, Wishlist)
from app.api import wants_json, api_ok

products_bp = Blueprint('products', __name__)

SORTS = {
    'newest':     'Newest',
    'price_asc':  'Price: Low to High',
    'price_desc': 'Price: High to Low',
    'rating':     'Top Rated',
    'name':       'Name A–Z',
}

# Claim filters exposed as ?claim=vegan&claim=fragrance_free
CLAIM_FILTERS = {
    'vegan':             ('Vegan', Product.is_vegan),
    'cruelty_free':      ('Cruelty-Free', Product.is_cruelty_free),
    'fragrance_free':    ('Fragrance-Free', Product.is_fragrance_free),
    'non_comedogenic':   ('Non-Comedogenic', Product.is_non_comedogenic),
    'dermatologist_tested': ('Dermatologist-Tested', Product.is_dermatologist_tested),
}


def _filter_options():
    """Everything the filter sidebar needs, in one place."""
    return {
        'categories':  Category.query.filter_by(parent_id=None)
                               .order_by(Category.sort_order, Category.name).all(),
        'all_categories': Category.query.order_by(Category.sort_order, Category.name).all(),
        'brands':      Brand.query.filter_by(is_active=True).order_by(Brand.name).all(),
        'skin_types':  SkinType.query.order_by(SkinType.skin_type_id).all(),
        'concerns':    SkinConcern.query.order_by(SkinConcern.name).all(),
        'ingredients': Ingredient.query.filter_by(is_active_ingredient=True)
                                 .order_by(Ingredient.name).all(),
        'product_types': Product.PRODUCT_TYPES,
        'routine_steps': Product.ROUTINE_STEPS,
        'claims':      {k: v[0] for k, v in CLAIM_FILTERS.items()},
        'sorts':       SORTS,
    }


def _apply_filters(query, f):
    """Narrow `query` by the parsed filter dict `f`. Shared by the HTML page and
    the JSON API so both always agree on what a filter means."""
    if f['category_id']:
        cat = Category.query.get(f['category_id'])
        if cat:
            # A parent category ('Face') shows everything filed under its children.
            query = query.filter(Product.category_id.in_(cat.descendant_ids()))
    if f['brand_ids']:
        query = query.filter(Product.brand_id.in_(f['brand_ids']))
    if f['product_type']:
        query = query.filter(Product.product_type == f['product_type'])
    if f['routine_step']:
        query = query.filter(Product.routine_step == f['routine_step'])
    if f['skin_type_id']:
        query = query.filter(Product.skin_types.any(SkinType.skin_type_id == f['skin_type_id']))
    for cid in f['concern_ids']:
        # AND across concerns — "acne AND dark spots" should narrow, not widen.
        query = query.filter(Product.concerns.any(SkinConcern.concern_id == cid))
    for iid in f['ingredient_ids']:
        query = query.filter(Product.ingredient_links.any(
            ProductIngredient.ingredient_id == iid))
    for claim in f['claim_keys']:
        query = query.filter(CLAIM_FILTERS[claim][1].is_(True))
    if f['min_price'] is not None:
        query = query.filter(Product.base_price >= f['min_price'])
    if f['max_price'] is not None:
        query = query.filter(Product.base_price <= f['max_price'])
    if f['spf_only']:
        query = query.filter(Product.spf.isnot(None))
    if f['in_stock']:
        query = query.filter(Product.variants.any(ProductVariant.stock > 0))
    if f['on_sale']:
        query = query.filter(Product.variants.any(
            ProductVariant.compare_at_price > ProductVariant.price))
    if f['search']:
        term = f'%{f["search"]}%'
        query = query.filter(or_(
            Product.name.ilike(term),
            Product.description.ilike(term),
            Product.product_type.ilike(term),
            Product.ingredients_full.ilike(term),
            Product.brand.has(Brand.name.ilike(term)),
        ))
    return query


def _parse_filters():
    args = request.args
    return {
        'category_id':  args.get('category', type=int),
        'brand_ids':    args.getlist('brand', type=int),
        'product_type': args.get('type', '').strip() or None,
        'routine_step': args.get('step', type=int),
        'skin_type_id': args.get('skin_type', type=int),
        'concern_ids':  args.getlist('concern', type=int),
        'ingredient_ids': args.getlist('ingredient', type=int),
        'claim_keys':   [c for c in args.getlist('claim') if c in CLAIM_FILTERS],
        'min_price':    args.get('min_price', type=float),
        'max_price':    args.get('max_price', type=float),
        'spf_only':     args.get('spf') == '1',
        'in_stock':     args.get('in_stock') == '1',
        'on_sale':      args.get('on_sale') == '1',
        'search':       args.get('q', '').strip(),
        'sort':         args.get('sort', 'newest'),
    }


def _sorted(query, sort):
    if sort == 'price_asc':
        return query.order_by(Product.base_price.asc())
    if sort == 'price_desc':
        return query.order_by(Product.base_price.desc())
    if sort == 'name':
        return query.order_by(Product.name.asc())
    if sort == 'rating':
        # Left-join the review average so unrated products fall to the bottom.
        avg = (db.session.query(Review.product_id.label('pid'),
                                func.avg(Review.rating).label('avg_rating'))
               .group_by(Review.product_id).subquery())
        return (query.outerjoin(avg, avg.c.pid == Product.product_id)
                     .order_by(avg.c.avg_rating.desc().nulls_last(),
                               Product.created_at.desc()))
    return query.order_by(Product.created_at.desc())


@products_bp.route('/')
def list_products():
    page = request.args.get('page', 1, type=int)
    f = _parse_filters()

    query = _apply_filters(Product.query.filter_by(is_active=True), f)
    query = _sorted(query, f['sort'])
    products = query.paginate(page=page, per_page=12, error_out=False)

    options = _filter_options()

    if wants_json():
        return api_ok({
            'products': [p.to_dict(include_variants=False) for p in products.items],
            'page': products.page,
            'pages': products.pages,
            'total': products.total,
            'filters': f,
            'options': {
                'categories': [c.to_dict(include_children=True) for c in options['categories']],
                'brands': [b.to_dict() for b in options['brands']],
                'skin_types': [s.to_dict() for s in options['skin_types']],
                'concerns': [c.to_dict() for c in options['concerns']],
                'ingredients': [i.to_dict() for i in options['ingredients']],
                'product_types': options['product_types'],
                'routine_steps': options['routine_steps'],
                'claims': options['claims'],
                'sorts': options['sorts'],
            },
        })

    return render_template('products/list.html', products=products, f=f, **options)


@products_bp.route('/<int:product_id>')
def detail(product_id):
    product = Product.query.get_or_404(product_id)

    review_skin_type = request.args.get('review_skin_type', type=int)
    review_query = Review.query.filter_by(product_id=product_id)
    if review_skin_type:
        review_query = review_query.filter_by(skin_type_id=review_skin_type)
    reviews = review_query.order_by(Review.created_at.desc()).all()

    # Rating histogram — 5★ down to 1★
    all_reviews = Review.query.filter_by(product_id=product_id).all()
    breakdown = {n: 0 for n in range(5, 0, -1)}
    for r in all_reviews:
        breakdown[r.rating] = breakdown.get(r.rating, 0) + 1

    # "Related" for skincare means shared concerns, not just a shared shelf.
    concern_ids = [c.concern_id for c in product.concerns]
    related_query = Product.query.filter(
        Product.product_id != product_id, Product.is_active.is_(True))
    if concern_ids:
        related_query = related_query.filter(
            Product.concerns.any(SkinConcern.concern_id.in_(concern_ids)))
    related = related_query.limit(4).all()
    if len(related) < 4:
        filler = Product.query.filter(
            Product.category_id == product.category_id,
            Product.product_id != product_id,
            Product.is_active.is_(True),
        ).limit(4 - len(related)).all()
        seen = {p.product_id for p in related}
        related += [p for p in filler if p.product_id not in seen]

    # The rest of the routine — one product per step, excluding this one.
    routine = []
    for step in sorted(Product.ROUTINE_STEPS):
        if step == product.routine_step:
            continue
        match = Product.query.filter(
            Product.routine_step == step,
            Product.product_id != product_id,
            Product.is_active.is_(True),
        )
        if concern_ids:
            preferred = match.filter(
                Product.concerns.any(SkinConcern.concern_id.in_(concern_ids))).first()
            if preferred:
                routine.append(preferred)
                continue
        found = match.first()
        if found:
            routine.append(found)

    in_wishlist = False
    if current_user.is_authenticated:
        wl = Wishlist.query.filter_by(user_id=current_user.user_id).first()
        in_wishlist = bool(wl and wl.has_product(product_id))

    if wants_json():
        return api_ok({
            'product': product.to_dict(include_detail=True),
            'reviews': [r.to_dict() for r in reviews],
            'rating_breakdown': breakdown,
            'related': [p.to_dict(include_variants=False) for p in related],
            'routine': [p.to_dict(include_variants=False) for p in routine],
            'in_wishlist': in_wishlist,
        })

    return render_template('products/detail.html',
                           product=product,
                           reviews=reviews,
                           breakdown=breakdown,
                           total_reviews=len(all_reviews),
                           related=related,
                           routine=routine,
                           in_wishlist=in_wishlist,
                           skin_types=SkinType.query.all(),
                           review_skin_type=review_skin_type)


@products_bp.route('/brand/<slug>')
def by_brand(slug):
    brand = Brand.query.filter_by(slug=slug).first_or_404()
    page = request.args.get('page', 1, type=int)
    products = (Product.query.filter_by(brand_id=brand.brand_id, is_active=True)
                .order_by(Product.created_at.desc())
                .paginate(page=page, per_page=12, error_out=False))
    if wants_json():
        return api_ok({
            'brand': brand.to_dict(),
            'products': [p.to_dict(include_variants=False) for p in products.items],
            'page': products.page, 'pages': products.pages, 'total': products.total,
        })
    return render_template('products/brand.html', brand=brand, products=products)


@products_bp.route('/concern/<slug>')
def by_concern(slug):
    concern = SkinConcern.query.filter_by(slug=slug).first_or_404()
    page = request.args.get('page', 1, type=int)
    products = (Product.query.filter(
                    Product.is_active.is_(True),
                    Product.concerns.any(SkinConcern.concern_id == concern.concern_id))
                .order_by(Product.routine_step.asc().nulls_last(), Product.base_price.asc())
                .paginate(page=page, per_page=12, error_out=False))
    if wants_json():
        return api_ok({
            'concern': concern.to_dict(),
            'products': [p.to_dict(include_variants=False) for p in products.items],
            'page': products.page, 'pages': products.pages, 'total': products.total,
        })
    return render_template('products/concern.html', concern=concern, products=products)


@products_bp.route('/ingredient/<slug>')
def by_ingredient(slug):
    ingredient = Ingredient.query.filter_by(slug=slug).first_or_404()
    products = (Product.query.filter(
                    Product.is_active.is_(True),
                    Product.ingredient_links.any(
                        ProductIngredient.ingredient_id == ingredient.ingredient_id))
                .order_by(Product.base_price.asc()).all())
    if wants_json():
        return api_ok({
            'ingredient': ingredient.to_dict(),
            'products': [p.to_dict(include_variants=False) for p in products],
        })
    return render_template('products/ingredient.html',
                           ingredient=ingredient, products=products)


@products_bp.route('/for-you')
def for_you():
    """Products matched to the signed-in customer's saved skin profile."""
    profile = current_user.skin_profile if current_user.is_authenticated else None
    if not profile:
        if wants_json():
            return api_ok({'products': [], 'profile': None,
                           'message': 'Set up a skin profile to get recommendations.'})
        return render_template('products/for_you.html', products=[], profile=None,
                               grouped=[])

    query = Product.query.filter(Product.is_active.is_(True))
    if profile.skin_type_id:
        query = query.filter(Product.skin_types.any(
            SkinType.skin_type_id == profile.skin_type_id))
    concern_ids = [c.concern_id for c in profile.concerns]
    if concern_ids:
        query = query.filter(Product.concerns.any(SkinConcern.concern_id.in_(concern_ids)))
    if profile.is_sensitive:
        query = query.filter(Product.is_fragrance_free.is_(True))
    matches = query.all()

    # Present them as a routine, in the order they'd actually be applied.
    grouped = []
    for step, label in sorted(Product.ROUTINE_STEPS.items()):
        step_products = [p for p in matches if p.routine_step == step]
        if step_products:
            grouped.append((step, label, step_products))

    if wants_json():
        return api_ok({
            'profile': profile.to_dict(),
            'products': [p.to_dict(include_variants=False) for p in matches],
            'routine': [{'step': s, 'label': l,
                         'products': [p.to_dict(include_variants=False) for p in ps]}
                        for s, l, ps in grouped],
        })
    return render_template('products/for_you.html', products=matches,
                           profile=profile, grouped=grouped)


@products_bp.route('/bundles')
def bundles():
    all_bundles = Bundle.query.filter_by(is_active=True).order_by(Bundle.price).all()
    if wants_json():
        return api_ok([b.to_dict() for b in all_bundles])
    return render_template('products/bundles.html', bundles=all_bundles)


@products_bp.route('/bundles/<slug>')
def bundle_detail(slug):
    bundle = Bundle.query.filter_by(slug=slug).first_or_404()
    if wants_json():
        return api_ok(bundle.to_dict())
    return render_template('products/bundle_detail.html', bundle=bundle)
