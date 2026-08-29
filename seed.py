"""
seed.py — populate the database with a full skincare catalog for development.
Run: python seed.py

Drops and recreates every table, then loads brands, the skincare taxonomies
(skin types, concerns, ingredients), products with variants and gallery
images, routine bundles, shipping methods, plus sample customers, orders,
reviews, wishlists and subscriptions.

Product photography is generated locally with Pillow into
app/static/images/skincare/ so the storefront never depends on an external
image host being reachable.
"""
import os, sys, textwrap, hashlib
sys.path.insert(0, os.path.dirname(__file__))

from run import app
from app.models import (
    db, User, Role, UserRole, Brand, Category, Product, ProductVariant,
    ProductImage, SkinType, SkinConcern, Ingredient, ProductIngredient,
    UserSkinProfile, Address, Wishlist, WishlistItem, Bundle, BundleItem,
    Cart, Coupon, Promotion, ShippingMethod, Order, OrderItem,
    OrderStatusHistory, Payment, Shipping, Review, InventoryLog,
    BackInStockAlert, ReturnRequest, ReturnItem, Subscription,
)
from app.utils import slugify
from datetime import datetime, timedelta, date

IMAGE_DIR = os.path.join(os.path.dirname(__file__), 'app', 'static', 'images', 'skincare')
IMAGE_REL = 'images/skincare'

# Shelf palette, keyed to the storefront theme (cream / sage / olive / terracotta)
# so generated tiles sit inside the page rather than fighting it.
PALETTES = [
    ((244, 232, 214), (223, 202, 172)),   # cream / sand
    ((221, 229, 182), (192, 206, 150)),   # pistachio
    ((232, 238, 218), (198, 213, 178)),   # pale olive
    ((248, 231, 214), (229, 193, 159)),   # terracotta wash
    ((250, 243, 231), (230, 216, 191)),   # warm white
    ((226, 234, 216), (186, 202, 172)),   # eucalyptus
]


def _font(size):
    from PIL import ImageFont
    for path in (r'C:\Windows\Fonts\segoeui.ttf', r'C:\Windows\Fonts\arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def make_image(slug, brand_name, product_name, kicker, variant_suffix=''):
    """Render a catalog tile for a product and return its /static-relative path."""
    from PIL import Image, ImageDraw

    os.makedirs(IMAGE_DIR, exist_ok=True)
    filename = f'{slug}{variant_suffix}.jpg'
    full_path = os.path.join(IMAGE_DIR, filename)
    rel_path = f'{IMAGE_REL}/{filename}'
    if os.path.exists(full_path):
        return rel_path

    W = H = 900
    seed_int = int(hashlib.md5(slug.encode()).hexdigest(), 16)
    top, bottom = PALETTES[seed_int % len(PALETTES)]

    img = Image.new('RGB', (W, H), top)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        draw.line([(0, y), (W, y)],
                  fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))

    # A soft light field behind the label so text stays legible on any palette.
    # Blurred and near-bleed on purpose: a crisp, inset disc reads as a coin at
    # thumbnail size rather than as product photography.
    from PIL import ImageFilter
    pad = 40
    overlay = Image.new('RGB', (W, H), (255, 255, 255))
    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).ellipse([pad, pad, W - pad, H - pad], fill=112)
    mask = mask.filter(ImageFilter.GaussianBlur(70))
    img = Image.composite(overlay, img, mask)
    draw = ImageDraw.Draw(img)

    ink = (37, 48, 31)      # --c-text
    muted = (116, 121, 95)  # --c-muted

    f_brand = _font(26)
    f_name = _font(52)
    f_kicker = _font(24)

    brand_text = ' '.join(brand_name.upper())
    bw = draw.textlength(brand_text, font=f_brand)
    draw.text(((W - bw) / 2, 300), brand_text, font=f_brand, fill=muted)

    lines = textwrap.wrap(product_name, width=16)[:3]
    y = 375
    for line in lines:
        lw = draw.textlength(line, font=f_name)
        draw.text(((W - lw) / 2, y), line, font=f_name, fill=ink)
        y += 64

    y += 14
    draw.line([(W / 2 - 40, y), (W / 2 + 40, y)], fill=muted, width=2)
    y += 24
    kw = draw.textlength(kicker, font=f_kicker)
    draw.text(((W - kw) / 2, y), kicker, font=f_kicker, fill=muted)

    img.save(full_path, 'JPEG', quality=88)
    return rel_path


def seed():
    with app.app_context():
        print("Dropping and recreating tables...")
        db.drop_all()
        db.create_all()

        # ── Roles ──────────────────────────────────────────────────────────────
        admin_role    = Role(role_name='Admin')
        customer_role = Role(role_name='Customer')
        staff_role    = Role(role_name='Staff')
        db.session.add_all([admin_role, customer_role, staff_role])
        db.session.flush()

        # ── Skin types ─────────────────────────────────────────────────────────
        skin_type_data = [
            ('Normal',       '🌿', 'Balanced, few concerns, comfortable most days.'),
            ('Dry',          '🍂', 'Tight, flaky, or rough — lacks oil.'),
            ('Oily',         '💧', 'Shiny by midday, prone to congestion.'),
            ('Combination',  '🌗', 'Oily T-zone with normal-to-dry cheeks.'),
            ('Sensitive',    '🌸', 'Reacts easily — stinging, redness, or itching.'),
            ('Acne-Prone',   '🔴', 'Frequent breakouts and clogged pores.'),
        ]
        skin_types = {}
        for name, icon, desc in skin_type_data:
            st = SkinType(name=name, slug=slugify(name), icon=icon, description=desc)
            db.session.add(st)
            skin_types[name] = st

        # ── Skin concerns ──────────────────────────────────────────────────────
        concern_data = [
            ('Acne & Breakouts',     '🎯', 'Whiteheads, blackheads and inflamed spots.'),
            ('Dark Spots',           '🟤', 'Post-acne marks and hyperpigmentation.'),
            ('Fine Lines & Wrinkles','〰️', 'Early signs of ageing and loss of firmness.'),
            ('Dryness & Dehydration','🏜️', 'Skin lacking oil, water, or both.'),
            ('Redness & Irritation', '🌡️', 'Reactive, flushed or compromised barrier.'),
            ('Large Pores',          '⚪', 'Visibly enlarged pores, usually in the T-zone.'),
            ('Dullness',             '✨', 'Tired-looking skin with no glow.'),
            ('Uneven Texture',       '🧱', 'Bumpy, rough or congested surface.'),
            ('Sun Damage',           '☀️', 'Photoageing, sunspots and uneven tone.'),
            ('Excess Oil',           '🫧', 'Overactive sebum and midday shine.'),
        ]
        concerns = {}
        for name, icon, desc in concern_data:
            c = SkinConcern(name=name, slug=slugify(name), icon=icon, description=desc)
            db.session.add(c)
            concerns[name] = c

        # ── Ingredients ────────────────────────────────────────────────────────
        ingredient_data = [
            # (name, INCI, benefits, is_active, caution)
            ('Niacinamide', 'Niacinamide',
             'Reduces the look of pores, balances oil and evens tone.', True, None),
            ('Hyaluronic Acid', 'Sodium Hyaluronate',
             'Holds water in the upper layers for immediate plumping.', True,
             'Apply to damp skin and seal with a moisturiser, or it can feel drying.'),
            ('Retinol', 'Retinol',
             'Speeds cell turnover; the best-studied anti-ageing active.', True,
             'Night use only. Introduce slowly and always pair with SPF. Avoid during pregnancy.'),
            ('Vitamin C', 'L-Ascorbic Acid',
             'Antioxidant that brightens and fades dark spots.', True,
             'Can sting on compromised skin. Do not layer directly with strong acids.'),
            ('Salicylic Acid', 'Salicylic Acid',
             'Oil-soluble BHA that clears inside the pore.', True,
             'Limit to once daily; over-use dries and irritates.'),
            ('Glycolic Acid', 'Glycolic Acid',
             'Small-molecule AHA that resurfaces and brightens.', True,
             'Increases sun sensitivity. Do not use with retinol on the same night.'),
            ('Lactic Acid', 'Lactic Acid',
             'Gentle AHA that exfoliates while hydrating.', True, None),
            ('Azelaic Acid', 'Azelaic Acid',
             'Calms redness and targets both acne and pigmentation.', True, None),
            ('Ceramides', 'Ceramide NP',
             'Rebuilds the skin barrier and stops water loss.', False, None),
            ('Centella Asiatica', 'Centella Asiatica Extract',
             'Soothes irritation and supports healing.', False, None),
            ('Squalane', 'Squalane',
             'Lightweight emollient that softens without clogging.', False, None),
            ('Panthenol', 'Panthenol',
             'Pro-vitamin B5 — hydrates and calms.', False, None),
            ('Peptides', 'Palmitoyl Tripeptide-1',
             'Signals the skin to firm and support collagen.', True, None),
            ('Zinc PCA', 'Zinc PCA',
             'Regulates sebum and reduces shine.', True, None),
            ('Green Tea Extract', 'Camellia Sinensis Leaf Extract',
             'Antioxidant that calms and protects.', False, None),
            ('Bakuchiol', 'Bakuchiol',
             'Plant-derived retinol alternative, safe for sensitive skin.', True, None),
            ('Snail Mucin', 'Snail Secretion Filtrate',
             'Hydrates and helps repair post-acne marks.', False, None),
            ('Allantoin', 'Allantoin',
             'Soothing agent that reduces roughness.', False, None),
            ('Tranexamic Acid', 'Tranexamic Acid',
             'Targets stubborn melasma and dark patches.', True, None),
            ('Alpha Arbutin', 'Alpha-Arbutin',
             'Brightens pigmentation without irritation.', True, None),
            ('Zinc Oxide', 'Zinc Oxide',
             'Mineral UV filter — broad spectrum and gentle.', True, None),
            ('Glycerin', 'Glycerin',
             'Classic humectant that draws water into skin.', False, None),
        ]
        ingredients = {}
        for name, inci, benefits, is_act, caution in ingredient_data:
            ing = Ingredient(name=name, inci_name=inci, slug=slugify(name),
                             benefits=benefits, is_active_ingredient=is_act,
                             caution_note=caution,
                             description=f'{name} ({inci}) — {benefits}')
            db.session.add(ing)
            ingredients[name] = ing

        # ── Brands ─────────────────────────────────────────────────────────────
        brand_data = [
            ('Lumière Labs', 'France',
             'Clinical French formulations built around a single hero active per product.'),
            ('Hanbit', 'South Korea',
             'K-beauty essentials: light layers, barrier-first, fragrance-free.'),
            ('Terra Botanica', 'Australia',
             'Plant-derived actives, refillable glass, certified cruelty-free.'),
            ('Dermé Clinical', 'United States',
             'Dermatologist-developed care for reactive and post-procedure skin.'),
            ('Ceraline', 'Germany',
             'Barrier repair specialists — ceramides, lipids and nothing superfluous.'),
            ('Solstice', 'Japan',
             'Sun care that people actually want to reapply.'),
        ]
        brands = {}
        for name, country, desc in brand_data:
            b = Brand(name=name, slug=slugify(name), country=country, description=desc)
            db.session.add(b)
            brands[name] = b
        db.session.flush()

        # ── Categories (two levels) ────────────────────────────────────────────
        category_tree = [
            ('Cleansers',          'Face', 'Gels, balms and foams that lift the day off.'),
            ('Toners & Essences',  'Face', 'Lightweight hydration and prep steps.'),
            ('Serums & Treatments','Face', 'Concentrated actives for a specific concern.'),
            ('Moisturizers',       'Face', 'Creams, gels and lotions that seal it all in.'),
            ('Eye Care',           'Face', 'Targeted care for the thinnest skin on the face.'),
            ('Masks & Exfoliants', 'Face', 'Weekly resets — clay, sheet and acid.'),
            ('Sunscreen',          None,   'Daily broad-spectrum protection.'),
            ('Body Care',          None,   'Lotions and washes from the neck down.'),
            ('Lip Care',           None,   'Balms and treatments for dry lips.'),
        ]
        cat_objs = {}
        face = Category(name='Face', slug='face', sort_order=0,
                        description='Everything for your facial routine.')
        db.session.add(face)
        db.session.flush()
        cat_objs['Face'] = face
        for i, (name, parent, desc) in enumerate(category_tree, start=1):
            c = Category(name=name, slug=slugify(name), description=desc, sort_order=i,
                         parent_id=cat_objs[parent].category_id if parent else None)
            db.session.add(c)
            cat_objs[name] = c
        db.session.flush()

        # ── Shipping methods ───────────────────────────────────────────────────
        shipping_methods = [
            ShippingMethod(name='Standard', description='Delivered by local courier.',
                           fee=2.50, free_over=35, eta_days_min=3, eta_days_max=5, sort_order=1),
            ShippingMethod(name='Express', description='Priority handling, next-day in Phnom Penh.',
                           fee=6.00, free_over=None, eta_days_min=1, eta_days_max=2, sort_order=2),
            ShippingMethod(name='Store Pickup', description='Collect from our Toul Kork counter.',
                           fee=0, free_over=None, eta_days_min=1, eta_days_max=1, sort_order=3),
        ]
        db.session.add_all(shipping_methods)
        db.session.flush()

        # ── Products ───────────────────────────────────────────────────────────
        # Each entry: dict describing one product plus its variants.
        P = [
            dict(name='Gentle Gel Cleanser', brand='Hanbit', category='Cleansers',
                 type='Cleanser', step=1, texture='Gel', price=16.00,
                 volume='150 ml', pao=12,
                 desc='A low-pH gel that removes sunscreen and grime without that squeaky, '
                      'stripped feeling. Rinses completely clean and leaves skin calm enough '
                      'for actives straight after.',
                 how='Morning and night, massage a coin-sized amount over damp skin for 30 '
                     'seconds, then rinse with lukewarm water. Follow with toner.',
                 inci='Water, Glycerin, Cocamidopropyl Betaine, Coco-Glucoside, Panthenol, '
                      'Centella Asiatica Extract, Allantoin, Sodium Hyaluronate, Citric Acid, '
                      'Sodium Benzoate, Potassium Sorbate.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Normal', 'Oily', 'Combination', 'Sensitive', 'Acne-Prone'],
                 concern=['Excess Oil', 'Redness & Irritation'],
                 key=[('Panthenol', '2%', True), ('Centella Asiatica', None, True),
                      ('Glycerin', None, False), ('Allantoin', None, False)],
                 variants=[('150 ml', None, 16.00, None, 64, 180),
                           ('300 ml', None, 26.00, 32.00, 28, 340),
                           ('Travel 50 ml', None, 7.00, None, 90, 70)]),

            dict(name='Melting Cleansing Balm', brand='Hanbit', category='Cleansers',
                 type='Cleanser', step=1, texture='Balm', price=22.00,
                 volume='100 ml', pao=12,
                 desc='A sherbet balm that turns to oil on contact and emulsifies to milk with '
                      'water. Dissolves long-wear SPF and makeup in one pass — the first half '
                      'of a double cleanse.',
                 how='On dry skin, massage a spatula-scoop over the face for a minute. Add '
                     'water to emulsify, rinse, then follow with a gel cleanser.',
                 inci='Ethylhexyl Palmitate, Caprylic/Capric Triglyceride, Squalane, '
                      'Polyglyceryl-3 Diisostearate, Sorbeth-30 Tetraoleate, Camellia Sinensis '
                      'Leaf Extract, Tocopherol.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=False, derm=False),
                 skin=['Normal', 'Dry', 'Combination', 'Sensitive'],
                 concern=['Dryness & Dehydration', 'Uneven Texture'],
                 key=[('Squalane', None, True), ('Green Tea Extract', None, True)],
                 variants=[('100 ml', None, 22.00, None, 41, 210)]),

            dict(name='Hydrating Essence Toner', brand='Hanbit', category='Toners & Essences',
                 type='Toner', step=2, texture='Water', price=19.00,
                 volume='200 ml', pao=12,
                 desc='A watery essence-toner hybrid you can layer two or three times. Preps '
                      'damp skin so everything applied after it absorbs instead of sitting on top.',
                 how='After cleansing, pat 2–3 layers into damp skin with your palms. Do not '
                     'wipe off. Follow with serum.',
                 inci='Water, Butylene Glycol, Glycerin, Snail Secretion Filtrate, Sodium '
                      'Hyaluronate, Panthenol, Betaine, Allantoin, Centella Asiatica Extract.',
                 claims=dict(vegan=False, cruelty=True, fragrance_free=True, non_comedo=True, derm=False),
                 skin=['Normal', 'Dry', 'Combination', 'Sensitive'],
                 concern=['Dryness & Dehydration', 'Dullness'],
                 key=[('Snail Mucin', '70%', True), ('Hyaluronic Acid', None, True),
                      ('Panthenol', None, False)],
                 variants=[('200 ml', None, 19.00, None, 55, 250),
                           ('400 ml', None, 32.00, 38.00, 19, 470)]),

            dict(name='Niacinamide 10% + Zinc Serum', brand='Lumière Labs',
                 category='Serums & Treatments',
                 type='Serum', step=3, texture='Serum', price=13.50,
                 volume='30 ml', pao=6,
                 desc='A high-strength niacinamide serum with zinc PCA for oil control. Visibly '
                      'tightens pores and calms the look of breakouts over four to six weeks.',
                 how='Apply 3–4 drops to clean, dry skin morning and night before moisturiser. '
                     'Start once daily if your skin is reactive.',
                 inci='Water, Niacinamide, Pentylene Glycol, Zinc PCA, Tamarindus Indica Seed '
                      'Gum, Xanthan Gum, Isoceteth-20, Ethoxydiglycol, Phenoxyethanol.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Oily', 'Combination', 'Acne-Prone', 'Normal'],
                 concern=['Large Pores', 'Excess Oil', 'Acne & Breakouts', 'Dark Spots'],
                 key=[('Niacinamide', '10%', True), ('Zinc PCA', '1%', True)],
                 variants=[('30 ml', None, 13.50, None, 120, 90),
                           ('60 ml', None, 22.00, None, 47, 160)]),

            dict(name='Vitamin C 15% Brightening Serum', brand='Lumière Labs',
                 category='Serums & Treatments',
                 type='Serum', step=3, texture='Serum', price=34.00,
                 volume='30 ml', pao=6,
                 desc='L-ascorbic acid at 15% with ferulic acid and vitamin E in an airless '
                      'pump. Fades post-acne marks and lifts dullness — the single best morning '
                      'antioxidant.',
                 how='Morning only. Apply 4 drops to dry skin before moisturiser, then always '
                     'follow with SPF. Store away from light.',
                 inci='Water, L-Ascorbic Acid, Propylene Glycol, Ethoxydiglycol, Ferulic Acid, '
                      'Tocopherol, Sodium Hyaluronate, Panthenol.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Normal', 'Oily', 'Combination', 'Dry'],
                 concern=['Dark Spots', 'Dullness', 'Sun Damage', 'Fine Lines & Wrinkles'],
                 key=[('Vitamin C', '15%', True), ('Hyaluronic Acid', None, False)],
                 variants=[('30 ml', None, 34.00, 40.00, 38, 95)]),

            dict(name='Retinol 0.3% Night Treatment', brand='Lumière Labs',
                 category='Serums & Treatments',
                 type='Serum', step=3, texture='Oil', price=29.00,
                 volume='30 ml', pao=6,
                 desc='Encapsulated retinol in a squalane base — the release is slowed so you '
                      'get the resurfacing without the peeling week. A true beginner strength.',
                 how='Night only, 2 nights a week to start, building to alternate nights. Apply '
                     'to dry skin, wait 10 minutes, then moisturise. SPF the next morning is '
                     'not optional.',
                 inci='Squalane, Caprylic/Capric Triglyceride, Retinol, Tocopherol, Simmondsia '
                      'Chinensis Seed Oil, Bisabolol.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Normal', 'Oily', 'Combination', 'Dry'],
                 concern=['Fine Lines & Wrinkles', 'Uneven Texture', 'Dark Spots', 'Large Pores'],
                 key=[('Retinol', '0.3%', True), ('Squalane', None, True)],
                 variants=[('30 ml', None, 29.00, None, 44, 92)]),

            dict(name='Bakuchiol Smoothing Serum', brand='Terra Botanica',
                 category='Serums & Treatments',
                 type='Serum', step=3, texture='Serum', price=27.00,
                 volume='30 ml', pao=12,
                 desc='A plant-derived alternative to retinol for skin that cannot tolerate it — '
                      'and for anyone pregnant or breastfeeding. Same smoothing brief, no '
                      'retinisation period.',
                 how='Morning or night on clean skin, before moisturiser. Safe to use daily '
                     'from the start.',
                 inci='Water, Glycerin, Bakuchiol, Squalane, Centella Asiatica Extract, '
                      'Panthenol, Sodium Hyaluronate, Xanthan Gum.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=False),
                 skin=['Sensitive', 'Dry', 'Normal', 'Combination'],
                 concern=['Fine Lines & Wrinkles', 'Uneven Texture', 'Redness & Irritation'],
                 key=[('Bakuchiol', '1%', True), ('Centella Asiatica', None, True),
                      ('Squalane', None, False)],
                 variants=[('30 ml', None, 27.00, None, 36, 90)]),

            dict(name='Azelaic Acid 10% Redness Cream', brand='Dermé Clinical',
                 category='Serums & Treatments',
                 type='Spot Treatment', step=3, texture='Cream', price=24.00,
                 volume='30 ml', pao=6,
                 desc='A cream-gel that works on two problems at once: the redness of reactive '
                      'skin and the marks left behind by breakouts. Gentle enough for daily use.',
                 how='Apply a thin layer to affected areas once or twice daily after cleansing. '
                     'A brief tingle on application is normal.',
                 inci='Water, Azelaic Acid, Dimethyl Isosorbide, Isodecyl Neopentanoate, '
                      'Dimethicone, Allantoin, Tocopherol.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Sensitive', 'Acne-Prone', 'Combination', 'Oily'],
                 concern=['Redness & Irritation', 'Dark Spots', 'Acne & Breakouts'],
                 key=[('Azelaic Acid', '10%', True), ('Allantoin', None, False)],
                 variants=[('30 ml', None, 24.00, None, 52, 88)]),

            dict(name='Alpha Arbutin + Tranexamic Brightening Drops', brand='Lumière Labs',
                 category='Serums & Treatments',
                 type='Ampoule', step=3, texture='Serum', price=26.00,
                 volume='30 ml', pao=6,
                 desc='For stubborn pigmentation that vitamin C alone has not shifted — melasma, '
                      'sun spots, and old acne marks. Works on the pathway, not the surface.',
                 how='Apply 3 drops morning and night to clean skin. Pair with daily SPF or the '
                     'pigment will simply return.',
                 inci='Water, Alpha-Arbutin, Tranexamic Acid, Propanediol, Niacinamide, '
                      'Sodium Hyaluronate, Panthenol, Phenoxyethanol.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Normal', 'Combination', 'Oily', 'Dry'],
                 concern=['Dark Spots', 'Sun Damage', 'Dullness'],
                 key=[('Alpha Arbutin', '2%', True), ('Tranexamic Acid', '3%', True),
                      ('Niacinamide', '4%', False)],
                 variants=[('30 ml', None, 26.00, None, 40, 90)]),

            dict(name='Hyaluronic Acid Hydration Serum', brand='Ceraline',
                 category='Serums & Treatments',
                 type='Serum', step=3, texture='Gel', price=18.00,
                 volume='30 ml', pao=12,
                 desc='Five molecular weights of hyaluronic acid so hydration reaches more than '
                      'just the top layer. Plumps fine dehydration lines within minutes.',
                 how='Apply to damp skin, then immediately seal with moisturiser. On dry skin '
                     'in a dry room it will pull moisture the wrong way.',
                 inci='Water, Sodium Hyaluronate, Sodium Hyaluronate Crosspolymer, Hydrolyzed '
                      'Hyaluronic Acid, Glycerin, Panthenol, Betaine, Allantoin.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Dry', 'Normal', 'Combination', 'Oily', 'Sensitive'],
                 concern=['Dryness & Dehydration', 'Fine Lines & Wrinkles', 'Dullness'],
                 key=[('Hyaluronic Acid', '2%', True), ('Panthenol', None, True),
                      ('Glycerin', None, False)],
                 variants=[('30 ml', None, 18.00, None, 88, 90),
                           ('50 ml', None, 26.00, None, 33, 130)]),

            dict(name='Ceramide Barrier Repair Cream', brand='Ceraline',
                 category='Moisturizers',
                 type='Moisturizer', step=4, texture='Cream', price=28.00,
                 volume='50 ml', pao=12,
                 desc='A rich but non-greasy cream with the ceramide-cholesterol-fatty acid '
                      'ratio your barrier actually uses. The one to reach for when actives have '
                      'gone too far.',
                 how='Apply as the last step at night, or under SPF in the morning. Warm between '
                     'palms and press in rather than rubbing.',
                 inci='Water, Glycerin, Caprylic/Capric Triglyceride, Cetearyl Alcohol, '
                      'Ceramide NP, Ceramide AP, Ceramide EOP, Cholesterol, Squalane, '
                      'Panthenol, Sodium Hyaluronate.',
                 claims=dict(vegan=False, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Dry', 'Sensitive', 'Normal', 'Combination'],
                 concern=['Dryness & Dehydration', 'Redness & Irritation', 'Uneven Texture'],
                 key=[('Ceramides', None, True), ('Squalane', None, True),
                      ('Panthenol', None, False)],
                 variants=[('50 ml', None, 28.00, None, 61, 140),
                           ('100 ml', None, 44.00, 52.00, 24, 250)]),

            dict(name='Oil-Free Gel Moisturizer', brand='Hanbit', category='Moisturizers',
                 type='Moisturizer', step=4, texture='Gel', price=21.00,
                 volume='50 ml', pao=12,
                 desc='A weightless water-gel for oily and humid-climate skin. Hydrates fully '
                      'and disappears — no film, no shine, no pilling under sunscreen.',
                 how='Apply a pea-sized amount morning and night as the final leave-on step '
                     'before SPF.',
                 inci='Water, Dimethicone, Glycerin, Butylene Glycol, Sodium Hyaluronate, '
                      'Niacinamide, Zinc PCA, Camellia Sinensis Leaf Extract, Carbomer.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Oily', 'Combination', 'Acne-Prone', 'Normal'],
                 concern=['Excess Oil', 'Large Pores', 'Dryness & Dehydration'],
                 key=[('Niacinamide', '3%', True), ('Hyaluronic Acid', None, True),
                      ('Green Tea Extract', None, False)],
                 variants=[('50 ml', None, 21.00, None, 73, 135)]),

            dict(name='Overnight Recovery Sleeping Mask', brand='Terra Botanica',
                 category='Moisturizers',
                 type='Mask', step=4, texture='Cream', price=32.00,
                 volume='75 ml', pao=12,
                 desc='A cushiony overnight layer that seals the whole routine in. Wake up with '
                      'the plumpness that usually only lasts an hour after moisturiser.',
                 how='Two to three nights a week, apply a generous layer as the final step. '
                     'Rinse in the morning if it feels heavy.',
                 inci='Water, Glycerin, Butylene Glycol, Squalane, Shea Butter, Ceramide NP, '
                      'Sodium Hyaluronate, Panthenol, Allantoin, Centella Asiatica Extract.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=False, non_comedo=False, derm=False),
                 skin=['Dry', 'Normal', 'Combination'],
                 concern=['Dryness & Dehydration', 'Dullness', 'Fine Lines & Wrinkles'],
                 key=[('Squalane', None, True), ('Ceramides', None, True)],
                 variants=[('75 ml', None, 32.00, None, 29, 190)]),

            dict(name='Peptide Firming Eye Cream', brand='Lumière Labs', category='Eye Care',
                 type='Eye Cream', step=3, texture='Cream', price=31.00,
                 volume='15 ml', pao=6,
                 desc='Caffeine for morning puffiness, peptides for the long game. Light enough '
                      'to wear under concealer without creasing.',
                 how='Tap a rice-grain amount around the orbital bone with your ring finger, '
                     'morning and night. Do not drag.',
                 inci='Water, Glycerin, Caffeine, Palmitoyl Tripeptide-1, Palmitoyl '
                      'Tetrapeptide-7, Sodium Hyaluronate, Squalane, Panthenol, Tocopherol.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Normal', 'Dry', 'Combination', 'Sensitive'],
                 concern=['Fine Lines & Wrinkles', 'Dullness', 'Dryness & Dehydration'],
                 key=[('Peptides', None, True), ('Hyaluronic Acid', None, False)],
                 variants=[('15 ml', None, 31.00, None, 42, 60)]),

            dict(name='Retinal Eye Renewal Balm', brand='Dermé Clinical', category='Eye Care',
                 type='Eye Cream', step=3, texture='Balm', price=38.00,
                 volume='15 ml', pao=6,
                 desc='A low-dose retinaldehyde balm formulated specifically for eye-area skin, '
                      'buffered with ceramides so it does not sting.',
                 how='Night only. Tap sparingly around the orbital bone 2–3 nights a week to '
                     'start. Stop if you get flaking and rebuild slowly.',
                 inci='Water, Caprylic/Capric Triglyceride, Retinal, Ceramide NP, Squalane, '
                      'Bisabolol, Panthenol, Tocopherol.',
                 claims=dict(vegan=False, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Normal', 'Dry', 'Combination'],
                 concern=['Fine Lines & Wrinkles', 'Dark Spots'],
                 key=[('Retinol', '0.05% retinal', True), ('Ceramides', None, True)],
                 variants=[('15 ml', None, 38.00, None, 21, 62)]),

            dict(name='BHA 2% Pore Clarifying Liquid', brand='Dermé Clinical',
                 category='Masks & Exfoliants',
                 type='Exfoliant', step=6, texture='Water', price=23.00,
                 volume='118 ml', pao=12,
                 desc='Salicylic acid gets inside the pore where oil actually sits — this is the '
                      'one for blackheads and the rough patches on the nose and chin.',
                 how='Once daily at night, sweep over clean dry skin with a cotton pad or '
                     'fingertips. Do not rinse. Start every other night.',
                 inci='Water, Methylpropanediol, Salicylic Acid, Butylene Glycol, Camellia '
                      'Sinensis Leaf Extract, Panthenol, Sodium Hydroxide, Allantoin.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Oily', 'Combination', 'Acne-Prone'],
                 concern=['Large Pores', 'Acne & Breakouts', 'Uneven Texture', 'Excess Oil'],
                 key=[('Salicylic Acid', '2%', True), ('Green Tea Extract', None, False)],
                 variants=[('118 ml', None, 23.00, None, 67, 170),
                           ('30 ml', None, 9.00, None, 110, 60)]),

            dict(name='AHA 8% Resurfacing Night Peel', brand='Lumière Labs',
                 category='Masks & Exfoliants',
                 type='Exfoliant', step=6, texture='Serum', price=25.00,
                 volume='30 ml', pao=6,
                 desc='A weekly glycolic and lactic blend that takes off the dull top layer. '
                      'Use it on a Sunday night and your Monday makeup sits differently.',
                 how='Once or twice a week at night, on clean dry skin. Leave 10 minutes, then '
                     'moisturise. Never on the same night as retinol. SPF the next day.',
                 inci='Water, Glycolic Acid, Lactic Acid, Propanediol, Sodium Hydroxide, '
                      'Panthenol, Allantoin, Centella Asiatica Extract, Tasmannia Lanceolata '
                      'Fruit Extract.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Normal', 'Oily', 'Combination'],
                 concern=['Dullness', 'Uneven Texture', 'Dark Spots', 'Large Pores'],
                 key=[('Glycolic Acid', '6%', True), ('Lactic Acid', '2%', True),
                      ('Allantoin', None, False)],
                 variants=[('30 ml', None, 25.00, None, 48, 92)]),

            dict(name='Kaolin Clay Detox Mask', brand='Terra Botanica',
                 category='Masks & Exfoliants',
                 type='Mask', step=6, texture='Cream', price=20.00,
                 volume='75 ml', pao=12,
                 desc='Kaolin and green clay draw out congestion without the cracked-plaster '
                      'dryness of a bentonite mask. Ten minutes, once a week.',
                 how='Apply an even layer to clean skin, avoiding the eyes. Leave 10 minutes '
                     'while still tacky — do not let it fully dry — then rinse warm.',
                 inci='Water, Kaolin, Illite, Glycerin, Zinc PCA, Camellia Sinensis Leaf '
                      'Extract, Panthenol, Allantoin, Xanthan Gum.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=False),
                 skin=['Oily', 'Combination', 'Acne-Prone'],
                 concern=['Excess Oil', 'Large Pores', 'Acne & Breakouts'],
                 key=[('Zinc PCA', None, True), ('Green Tea Extract', None, False)],
                 variants=[('75 ml', None, 20.00, None, 39, 200)]),

            dict(name='Calming Centella Sheet Mask', brand='Hanbit',
                 category='Masks & Exfoliants',
                 type='Mask', step=6, texture='Water', price=3.50,
                 volume='25 ml', pao=6,
                 desc='A cupra sheet soaked in centella essence — for the day after a peel, a '
                      'long flight, or too much sun.',
                 how='On clean skin, apply for 15–20 minutes. Remove and pat in the remaining '
                     'essence. Do not rinse.',
                 inci='Water, Butylene Glycol, Glycerin, Centella Asiatica Extract, Panthenol, '
                      'Allantoin, Sodium Hyaluronate, Madecassoside.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=False),
                 skin=['Sensitive', 'Dry', 'Normal', 'Combination', 'Acne-Prone'],
                 concern=['Redness & Irritation', 'Dryness & Dehydration'],
                 key=[('Centella Asiatica', None, True), ('Panthenol', None, True)],
                 variants=[('Single', None, 3.50, None, 240, 30),
                           ('Box of 10', None, 29.00, 35.00, 45, 300)]),

            dict(name='Daily Mineral Sunscreen SPF 50', brand='Solstice', category='Sunscreen',
                 type='Sunscreen', step=5, texture='Lotion', price=25.00,
                 volume='50 ml', pao=12, spf=50,
                 desc='A non-nano zinc sunscreen that finishes matte and, crucially, leaves no '
                      'white cast on medium-to-deep skin. Safe for post-procedure and reactive skin.',
                 how='Last step every morning. Two fingers for face and neck. Reapply every two '
                     'hours outdoors.',
                 inci='Zinc Oxide (non-nano) 22%, Water, Caprylic/Capric Triglyceride, Glycerin, '
                      'Silica, Niacinamide, Tocopherol, Bisabolol.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Sensitive', 'Acne-Prone', 'Normal', 'Combination', 'Dry', 'Oily'],
                 concern=['Sun Damage', 'Redness & Irritation', 'Dark Spots'],
                 key=[('Zinc Oxide', '22%', True), ('Niacinamide', '2%', False)],
                 variants=[('50 ml', None, 25.00, None, 95, 130),
                           ('Travel 15 ml', None, 9.50, None, 140, 45)]),

            dict(name='Invisible Fluid Sunscreen SPF 50+', brand='Solstice', category='Sunscreen',
                 type='Sunscreen', step=5, texture='Water', price=29.00,
                 volume='50 ml', pao=12, spf=50,
                 desc='A watery chemical filter fluid that vanishes on application. The one for '
                      'people who have given up on sunscreen because of the texture.',
                 how='Apply generously as the final morning step, before makeup. Reapply through '
                     'the day with the travel size.',
                 inci='Water, Alcohol Denat., Uvinul A Plus, Tinosorb S, Uvinul T150, Glycerin, '
                      'Butylene Glycol, Panthenol, Tocopherol.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Oily', 'Combination', 'Normal', 'Acne-Prone'],
                 concern=['Sun Damage', 'Excess Oil'],
                 key=[('Panthenol', None, False)],
                 variants=[('50 ml', None, 29.00, None, 78, 125),
                           ('Travel 15 ml', None, 11.00, None, 0, 45)]),   # out of stock on purpose

            dict(name='Tinted Sunscreen SPF 40', brand='Solstice', category='Sunscreen',
                 type='Sunscreen', step=5, texture='Cream', price=32.00,
                 volume='40 ml', pao=12, spf=40,
                 desc='Sheer mineral tint that evens tone enough to skip foundation. Four shades '
                      'blended to disappear rather than match exactly.',
                 how='Apply as the last morning step. Blend from the centre of the face outward. '
                     'Can be layered for more coverage.',
                 inci='Zinc Oxide 18%, Water, Caprylic/Capric Triglyceride, Iron Oxides, '
                      'Glycerin, Squalane, Tocopherol, Niacinamide.',
                 claims=dict(vegan=True, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Normal', 'Combination', 'Dry', 'Sensitive'],
                 concern=['Sun Damage', 'Dark Spots', 'Redness & Irritation'],
                 key=[('Zinc Oxide', '18%', True), ('Squalane', None, False)],
                 variants=[('40 ml', 'Fair', 32.00, None, 24, 110),
                           ('40 ml', 'Light', 32.00, None, 31, 110),
                           ('40 ml', 'Medium', 32.00, None, 27, 110),
                           ('40 ml', 'Deep', 32.00, None, 18, 110)]),

            dict(name='Urea 10% Smoothing Body Lotion', brand='Ceraline', category='Body Care',
                 type='Moisturizer', step=4, texture='Lotion', price=19.00,
                 volume='250 ml', pao=12,
                 desc='For keratosis pilaris on the arms and the rough patches on heels and '
                      'elbows. Urea both hydrates and gently dissolves the buildup.',
                 how='Apply daily to damp skin after showering. Avoid freshly shaved skin.',
                 inci='Water, Urea, Glycerin, Cetearyl Alcohol, Ceramide NP, Lactic Acid, '
                      'Squalane, Panthenol, Allantoin.',
                 claims=dict(vegan=False, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Dry', 'Normal', 'Sensitive'],
                 concern=['Dryness & Dehydration', 'Uneven Texture'],
                 key=[('Ceramides', None, True), ('Lactic Acid', '3%', True)],
                 variants=[('250 ml', None, 19.00, None, 56, 290),
                           ('500 ml', None, 30.00, 36.00, 22, 560)]),

            dict(name='Barrier Repair Lip Balm', brand='Ceraline', category='Lip Care',
                 type='Lip Care', step=4, texture='Balm', price=8.50,
                 volume='15 ml', pao=12,
                 desc='An unscented, untinted overnight lip mask that actually stays put. No '
                      'menthol, no camphor, nothing that makes you reapply every ten minutes.',
                 how='Apply generously before bed and as needed through the day.',
                 inci='Caprylic/Capric Triglyceride, Shea Butter, Squalane, Ceramide NP, '
                      'Panthenol, Tocopherol, Bisabolol.',
                 claims=dict(vegan=False, cruelty=True, fragrance_free=True, non_comedo=True, derm=True),
                 skin=['Dry', 'Sensitive', 'Normal', 'Combination', 'Oily', 'Acne-Prone'],
                 concern=['Dryness & Dehydration'],
                 key=[('Ceramides', None, True), ('Squalane', None, True)],
                 variants=[('15 ml', None, 8.50, None, 132, 40)]),
        ]

        products = {}
        print(f"Creating {len(P)} products (generating catalog imagery)…")
        for entry in P:
            slug = slugify(entry['name'])
            claims = entry.get('claims', {})
            product = Product(
                category_id  = cat_objs[entry['category']].category_id,
                brand_id     = brands[entry['brand']].brand_id,
                name         = entry['name'],
                slug         = slug,
                description  = entry['desc'],
                base_price   = entry['price'],
                product_type = entry['type'],
                routine_step = entry['step'],
                texture      = entry['texture'],
                how_to_use   = entry['how'],
                ingredients_full = entry['inci'],
                spf          = entry.get('spf'),
                pao_months   = entry.get('pao'),
                volume_label = entry.get('volume'),
                is_vegan               = claims.get('vegan', False),
                is_cruelty_free        = claims.get('cruelty', False),
                is_fragrance_free      = claims.get('fragrance_free', False),
                is_non_comedogenic     = claims.get('non_comedo', False),
                is_dermatologist_tested = claims.get('derm', False),
            )
            db.session.add(product)
            db.session.flush()
            products[entry['name']] = product

            # Taxonomy links
            for st in entry['skin']:
                product.skin_types.append(skin_types[st])
            for cn in entry['concern']:
                product.concerns.append(concerns[cn])
            for ing_name, conc, is_key in entry['key']:
                db.session.add(ProductIngredient(
                    product_id=product.product_id,
                    ingredient_id=ingredients[ing_name].ingredient_id,
                    concentration=conc, is_key=is_key))

            # Gallery — a front-of-pack tile plus a texture/ingredient card
            main = make_image(slug, entry['brand'], entry['name'], entry['type'])
            texture_img = make_image(slug, entry['brand'], entry['texture'] + ' Texture',
                                     entry['type'], variant_suffix='-texture')
            key_names = [k[0] for k in entry['key'] if k[2]] or [entry['type']]
            ing_img = make_image(slug, entry['brand'], ' + '.join(key_names[:2]),
                                 'Key Ingredients', variant_suffix='-ingredients')
            for i, (url, alt) in enumerate([
                (main, f'{entry["name"]} packaging'),
                (texture_img, f'{entry["name"]} texture'),
                (ing_img, f'{entry["name"]} key ingredients'),
            ]):
                db.session.add(ProductImage(product_id=product.product_id, url=url,
                                            alt_text=alt, sort_order=i, is_primary=(i == 0)))

            # Variants
            brand_code = ''.join(w[0] for w in entry['brand'].split())[:3].upper()
            for idx, (vol, shade, price, compare, stock, weight) in enumerate(entry['variants'], 1):
                variant = ProductVariant(
                    product_id  = product.product_id,
                    sku         = f'{brand_code}-{slug[:14].upper().replace("-", "")}-{idx:02d}',
                    volume      = vol,
                    shade       = shade,
                    price       = price,
                    compare_at_price = compare,
                    stock       = stock,
                    weight_grams = weight,
                    batch_no    = f'B{datetime.utcnow():%y%m}{product.product_id:03d}{idx}',
                    expiry_date = (datetime.utcnow() + timedelta(days=540 + idx * 30)).date(),
                    image       = main,
                )
                db.session.add(variant)
                db.session.flush()
                db.session.add(InventoryLog(variant_id=variant.variant_id, change_type='IN',
                                            quantity=stock, reference='initial stock'))
        db.session.flush()

        # ── Users ──────────────────────────────────────────────────────────────
        admin = User(name='Admin User', email='admin@shop.com', phone='+855 12 000 100')
        admin.set_password('admin123')
        admin.roles.append(admin_role)
        admin.roles.append(customer_role)

        alice = User(name='Alice Johnson', email='alice@example.com', phone='+855 12 000 101')
        alice.set_password('password')
        alice.roles.append(customer_role)

        bob = User(name='Bob Smith', email='bob@example.com', phone='+855 12 000 102')
        bob.set_password('password')
        bob.roles.append(customer_role)

        maya = User(name='Maya Chen', email='maya@example.com', phone='+855 12 000 103')
        maya.set_password('password')
        maya.roles.append(customer_role)

        db.session.add_all([admin, alice, bob, maya])
        db.session.flush()

        for u in [admin, alice, bob, maya]:
            db.session.add(Cart(user_id=u.user_id))
            db.session.add(Wishlist(user_id=u.user_id))
        db.session.flush()

        # ── Skin profiles ──────────────────────────────────────────────────────
        profiles = [
            (alice, 'Combination', '25-34', 'Light', False,
             ['Large Pores', 'Dark Spots', 'Dullness'], None),
            (bob, 'Oily', '18-24', 'Medium', False,
             ['Acne & Breakouts', 'Excess Oil'], None),
            (maya, 'Sensitive', '35-44', 'Fair', True,
             ['Redness & Irritation', 'Fine Lines & Wrinkles'], 'fragrance, essential oils'),
        ]
        for user, st_name, age, tone, sensitive, concern_names, allergies in profiles:
            prof = UserSkinProfile(
                user_id=user.user_id, skin_type_id=skin_types[st_name].skin_type_id,
                age_range=age, skin_tone=tone, is_sensitive=sensitive, allergies=allergies)
            db.session.add(prof)
            db.session.flush()
            for cn in concern_names:
                prof.concerns.append(concerns[cn])

        # ── Addresses ──────────────────────────────────────────────────────────
        addresses = [
            Address(user_id=alice.user_id, label='Home', recipient_name='Alice Johnson',
                    phone='+855 12 000 101', line1='No. 42, Street 310', line2='Boeung Keng Kang 1',
                    city='Phnom Penh', postal_code='12302', country='Cambodia', is_default=True),
            Address(user_id=alice.user_id, label='Work', recipient_name='Alice Johnson',
                    phone='+855 12 000 101', line1='Vattanac Capital, Level 12',
                    line2='No. 66 Monivong Blvd', city='Phnom Penh', postal_code='12202',
                    country='Cambodia', is_default=False),
            Address(user_id=bob.user_id, label='Home', recipient_name='Bob Smith',
                    phone='+855 12 000 102', line1='No. 8, Street 63', city='Phnom Penh',
                    postal_code='12000', country='Cambodia', is_default=True),
            Address(user_id=maya.user_id, label='Home', recipient_name='Maya Chen',
                    phone='+855 12 000 103', line1='No. 155, Street 271', city='Phnom Penh',
                    postal_code='12157', country='Cambodia', is_default=True),
        ]
        db.session.add_all(addresses)
        db.session.flush()

        # ── Wishlists ──────────────────────────────────────────────────────────
        wl_alice = Wishlist.query.filter_by(user_id=alice.user_id).first()
        wl_bob   = Wishlist.query.filter_by(user_id=bob.user_id).first()
        for name in ['Retinol 0.3% Night Treatment', 'Peptide Firming Eye Cream',
                     'Tinted Sunscreen SPF 40']:
            db.session.add(WishlistItem(wishlist_id=wl_alice.wishlist_id,
                                        product_id=products[name].product_id))
        for name in ['BHA 2% Pore Clarifying Liquid', 'Kaolin Clay Detox Mask']:
            db.session.add(WishlistItem(wishlist_id=wl_bob.wishlist_id,
                                        product_id=products[name].product_id))

        # ── Bundles / routine kits ─────────────────────────────────────────────
        def first_variant(product_name):
            return products[product_name].variants.first()

        bundle_data = [
            ('Acne Starter Routine',
             'The four steps that clear most mild breakouts — cleanse, treat, hydrate, protect. '
             'Everything fragrance-free and non-comedogenic.',
             52.00,
             ['Gentle Gel Cleanser', 'Niacinamide 10% + Zinc Serum',
              'Oil-Free Gel Moisturizer', 'Daily Mineral Sunscreen SPF 50']),
            ('Sensitive Skin Rescue Set',
             'For a barrier that has had enough. No acids, no fragrance, nothing that stings.',
             62.00,
             ['Melting Cleansing Balm', 'Azelaic Acid 10% Redness Cream',
              'Ceramide Barrier Repair Cream', 'Calming Centella Sheet Mask']),
            ('Brightening Duo',
             'Morning vitamin C and evening arbutin — the pairing that actually shifts dark spots.',
             54.00,
             ['Vitamin C 15% Brightening Serum', 'Alpha Arbutin + Tranexamic Brightening Drops']),
            ('Anti-Ageing Night Ritual',
             'Retinol, peptides and a barrier cream to buffer them. Build up slowly.',
             84.00,
             ['Retinol 0.3% Night Treatment', 'Peptide Firming Eye Cream',
              'Ceramide Barrier Repair Cream']),
        ]
        for name, desc, price, member_names in bundle_data:
            slug = slugify(name)
            bundle = Bundle(name=name, slug=slug, description=desc, price=price,
                            image=make_image(slug, 'Routine Kit', name, 'Bundle'))
            db.session.add(bundle)
            db.session.flush()
            for m in member_names:
                db.session.add(BundleItem(bundle_id=bundle.bundle_id,
                                          variant_id=first_variant(m).variant_id, quantity=1))

        # ── Coupons ────────────────────────────────────────────────────────────
        coupons = [
            Coupon(code='WELCOME10', discount_type='percentage', discount_value=10,
                   min_amount=0,   expiry_date=datetime.utcnow() + timedelta(days=365)),
            Coupon(code='GLOW20',   discount_type='percentage', discount_value=20,
                   min_amount=80,  expiry_date=datetime.utcnow() + timedelta(days=180)),
            Coupon(code='FLAT15',   discount_type='fixed',      discount_value=15,
                   min_amount=60,  expiry_date=datetime.utcnow() + timedelta(days=90)),
        ]
        db.session.add_all(coupons)
        db.session.flush()

        # ── Promotions ─────────────────────────────────────────────────────────
        promo = Promotion(
            name='Sun Care Season',
            discount_percent=15,
            start_date=datetime.utcnow() - timedelta(days=2),
            end_date=datetime.utcnow() + timedelta(days=28)
        )
        db.session.add(promo)
        db.session.flush()
        for p in products.values():
            if p.category.name == 'Sunscreen':
                promo.products.append(p)

        # ── Reviews ────────────────────────────────────────────────────────────
        review_data = [
            (alice, 'Niacinamide 10% + Zinc Serum', 5, 'Pores on my nose are genuinely smaller',
             'Six weeks in and the difference around my nose and chin is obvious in photos. '
             'No irritation at all, layers fine under sunscreen.', 'Combination', '25-34', True),
            (bob, 'Niacinamide 10% + Zinc Serum', 4, 'Good, but go slow',
             'Works well for oil control. I went straight to twice a day and got a bit red for '
             'the first week — once a day would have been smarter.', 'Oily', '18-24', True),
            (maya, 'Ceramide Barrier Repair Cream', 5, 'Saved my skin after a bad reaction',
             'I over-exfoliated and everything was stinging. This was the only thing I could put '
             'on without flinching. Back to normal in about five days.', 'Sensitive', '35-44', True),
            (alice, 'Vitamin C 15% Brightening Serum', 4, 'Real results on old acne marks',
             'Marks from last year have faded noticeably. Docking one star because it does '
             'oxidise faster than I would like once opened.', 'Combination', '25-34', True),
            (bob, 'BHA 2% Pore Clarifying Liquid', 5, 'Blackheads gone',
             'Every other night on my nose and chin. Cleared out congestion nothing else touched.',
             'Oily', '18-24', True),
            (maya, 'Daily Mineral Sunscreen SPF 50', 5, 'No white cast, no sting',
             'Mineral sunscreens usually leave me grey and itchy. This one does neither. '
             'I have repurchased twice.', 'Sensitive', '35-44', True),
            (alice, 'Daily Mineral Sunscreen SPF 50', 4, 'Great, slightly matte',
             'Lovely under makeup. On very dry winter days I need a richer moisturiser under it.',
             'Combination', '25-34', True),
            (maya, 'Bakuchiol Smoothing Serum', 4, 'Retinol without the drama',
             'I cannot tolerate retinol at all. Three months of this and my texture is smoother '
             'with zero flaking.', 'Sensitive', '35-44', False),
            (bob, 'Oil-Free Gel Moisturizer', 5, 'Perfect for this climate',
             'Disappears instantly, no shine by lunchtime. Exactly what I wanted.',
             'Oily', '18-24', True),
        ]
        for user, prod_name, rating, title, comment, st_name, age, verified in review_data:
            db.session.add(Review(
                user_id=user.user_id, product_id=products[prod_name].product_id,
                rating=rating, title=title, comment=comment,
                skin_type_id=skin_types[st_name].skin_type_id, age_range=age,
                is_verified_purchase=verified,
                created_at=datetime.utcnow() - timedelta(days=len(title) % 40)))

        # ── Sample orders ──────────────────────────────────────────────────────
        standard = shipping_methods[0]

        def make_order(user, address, lines, status, days_ago, coupon=None, method='KHQR'):
            """lines: [(product_name, variant_index, qty)]"""
            subtotal = 0.0
            resolved = []
            for prod_name, v_idx, qty in lines:
                variant = products[prod_name].variants.all()[v_idx]
                subtotal += float(variant.price) * qty
                resolved.append((variant, qty))
            discount = round(subtotal - coupon.apply(subtotal), 2) if coupon else 0.0
            after_discount = subtotal - discount
            ship_fee = standard.fee_for(after_discount)
            total = round(after_discount + ship_fee, 2)
            created = datetime.utcnow() - timedelta(days=days_ago)

            order = Order(
                user_id=user.user_id,
                coupon_id=coupon.coupon_id if coupon else None,
                shipping_method_id=standard.method_id,
                subtotal=round(subtotal, 2), discount_amount=discount,
                shipping_fee=ship_fee, tax=0, total_amount=total,
                status='Pending', created_at=created)
            db.session.add(order)
            db.session.flush()

            for variant, qty in resolved:
                db.session.add(OrderItem(
                    order_id=order.order_id, variant_id=variant.variant_id, quantity=qty,
                    price=variant.price, product_name=variant.product.name,
                    variant_label=variant.label()))
                variant.stock = max(0, variant.stock - qty)
                db.session.add(InventoryLog(
                    variant_id=variant.variant_id, change_type='OUT', quantity=qty,
                    reference=f'order_{order.order_id}', created_at=created))

            db.session.add(Payment(
                order_id=order.order_id, method=method, amount=total,
                status='Paid' if status in ('Shipped', 'Delivered') else 'Pending',
                paid_at=created if status in ('Shipped', 'Delivered') else None))
            db.session.add(Shipping(
                order_id=order.order_id, recipient_name=address.recipient_name,
                address=', '.join(p for p in [address.line1, address.line2] if p),
                city=address.city, postal_code=address.postal_code, country=address.country,
                phone=address.phone,
                status={'Delivered': 'Delivered', 'Shipped': 'Shipped'}.get(status, 'Preparing'),
                tracking_number=f'KH{order.order_id:07d}' if status in ('Shipped', 'Delivered') else None,
                carrier='VET Express' if status in ('Shipped', 'Delivered') else None,
                shipped_at=created + timedelta(days=1) if status in ('Shipped', 'Delivered') else None,
                delivered_at=created + timedelta(days=3) if status == 'Delivered' else None))

            # Walk the status trail so history looks real
            trail = Order.STATUS_CHOICES[:Order.STATUS_CHOICES.index(status) + 1] \
                if status in Order.STATUS_CHOICES else ['Pending']
            prev = None
            for i, s in enumerate(trail):
                db.session.add(OrderStatusHistory(
                    order_id=order.order_id, from_status=prev, to_status=s,
                    note='Seeded order history', changed_by_user_id=admin.user_id,
                    created_at=created + timedelta(days=i)))
                prev = s
            order.status = status
            return order

        o1 = make_order(alice, addresses[0],
                        [('Niacinamide 10% + Zinc Serum', 0, 1),
                         ('Daily Mineral Sunscreen SPF 50', 0, 1),
                         ('Gentle Gel Cleanser', 0, 1)],
                        'Delivered', 24, coupon=coupons[0])
        o2 = make_order(bob, addresses[2],
                        [('BHA 2% Pore Clarifying Liquid', 0, 1),
                         ('Oil-Free Gel Moisturizer', 0, 1)],
                        'Delivered', 15)
        o3 = make_order(maya, addresses[3],
                        [('Ceramide Barrier Repair Cream', 0, 1),
                         ('Calming Centella Sheet Mask', 1, 1),
                         ('Azelaic Acid 10% Redness Cream', 0, 1)],
                        'Shipped', 4, coupon=coupons[2])
        o4 = make_order(alice, addresses[0],
                        [('Vitamin C 15% Brightening Serum', 0, 1),
                         ('Hyaluronic Acid Hydration Serum', 0, 1)],
                        'Processing', 1)
        db.session.flush()

        # ── A return on the delivered order ────────────────────────────────────
        ret = ReturnRequest(
            order_id=o2.order_id, user_id=bob.user_id, status='Approved',
            reason='Skin reaction / irritation',
            details='The BHA stung badly after two nights and my cheeks went red and flaky.',
            created_at=datetime.utcnow() - timedelta(days=9))
        db.session.add(ret)
        db.session.flush()
        bha_item = o2.items.filter(OrderItem.product_name.like('BHA%')).first()
        if bha_item:
            db.session.add(ReturnItem(return_id=ret.return_id,
                                      order_item_id=bha_item.order_item_id, quantity=1))
            ret.refund_amount = float(bha_item.price)

        # ── Back-in-stock alerts on the deliberately empty variant ─────────────
        sold_out = products['Invisible Fluid Sunscreen SPF 50+'].variants.all()[1]
        db.session.add_all([
            BackInStockAlert(variant_id=sold_out.variant_id, user_id=alice.user_id,
                             email=alice.email),
            BackInStockAlert(variant_id=sold_out.variant_id, user_id=maya.user_id,
                             email=maya.email),
        ])

        # ── Subscriptions ──────────────────────────────────────────────────────
        db.session.add_all([
            Subscription(user_id=alice.user_id,
                         variant_id=first_variant('Daily Mineral Sunscreen SPF 50').variant_id,
                         address_id=addresses[0].address_id, quantity=1, interval_days=60,
                         discount_percent=10, status='Active',
                         next_delivery_at=datetime.utcnow() + timedelta(days=21)),
            Subscription(user_id=bob.user_id,
                         variant_id=first_variant('Gentle Gel Cleanser').variant_id,
                         address_id=addresses[2].address_id, quantity=1, interval_days=30,
                         discount_percent=10, status='Active',
                         next_delivery_at=datetime.utcnow() + timedelta(days=8)),
        ])

        db.session.commit()

        print("[OK] Seed complete!")
        print(f"  Brands:      {Brand.query.count()}")
        print(f"  Categories:  {Category.query.count()}  (2 levels)")
        print(f"  Products:    {Product.query.count()}  /  {ProductVariant.query.count()} variants")
        print(f"  Ingredients: {Ingredient.query.count()}   Skin types: {SkinType.query.count()}"
              f"   Concerns: {SkinConcern.query.count()}")
        print(f"  Bundles:     {Bundle.query.count()}   Orders: {Order.query.count()}"
              f"   Reviews: {Review.query.count()}")
        print(f"  Images:      {ProductImage.query.count()} generated into static/{IMAGE_REL}/")
        print()
        print("  Admin login: admin@shop.com / admin123")
        print("  User login:  alice@example.com / password  (also bob@, maya@)")
        print("  Coupons:     WELCOME10, GLOW20, FLAT15")


if __name__ == '__main__':
    seed()
