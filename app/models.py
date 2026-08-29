from datetime import datetime
from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from flask_bcrypt import Bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

db = SQLAlchemy()
bcrypt = Bcrypt()

# ─── Many-to-Many: Users ↔ Roles ───────────────────────────────────────────────
class UserRole(db.Model):
    __tablename__ = 'user_roles'
    user_role_id = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    role_id      = db.Column(db.Integer, db.ForeignKey('roles.role_id'), nullable=False)

# ─── Many-to-Many: Products ↔ Promotions ───────────────────────────────────────
class ProductPromotion(db.Model):
    __tablename__ = 'product_promotions'
    id           = db.Column(db.Integer, primary_key=True)
    product_id   = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    promotion_id = db.Column(db.Integer, db.ForeignKey('promotions.promotion_id'), nullable=False)

# ─── Many-to-Many: Products ↔ Skin Types ───────────────────────────────────────
class ProductSkinType(db.Model):
    __tablename__ = 'product_skin_types'
    id           = db.Column(db.Integer, primary_key=True)
    product_id   = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    skin_type_id = db.Column(db.Integer, db.ForeignKey('skin_types.skin_type_id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('product_id', 'skin_type_id', name='uq_product_skin_type'),)

# ─── Many-to-Many: Products ↔ Skin Concerns ────────────────────────────────────
class ProductConcern(db.Model):
    __tablename__ = 'product_concerns'
    id         = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    concern_id = db.Column(db.Integer, db.ForeignKey('skin_concerns.concern_id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('product_id', 'concern_id', name='uq_product_concern'),)

# ─── Many-to-Many: Skin Profiles ↔ Skin Concerns ───────────────────────────────
class SkinProfileConcern(db.Model):
    __tablename__ = 'skin_profile_concerns'
    id         = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey('user_skin_profiles.profile_id'), nullable=False)
    concern_id = db.Column(db.Integer, db.ForeignKey('skin_concerns.concern_id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('profile_id', 'concern_id', name='uq_profile_concern'),)


# ─── 1. Users ──────────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    user_id    = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False)
    email      = db.Column(db.String(180), unique=True, nullable=False)
    password   = db.Column(db.String(256), nullable=False)
    phone      = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Overrides UserMixin.is_active — Flask-Login refuses login_user() when this
    # is False, so deactivating an account here locks it out everywhere.
    is_active  = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    roles       = db.relationship('Role', secondary='user_roles', backref='users', lazy='dynamic')
    orders      = db.relationship('Order', backref='user', lazy='dynamic')
    reviews     = db.relationship('Review', backref='user', lazy='dynamic')
    cart        = db.relationship('Cart', backref='user', uselist=False)
    wishlist    = db.relationship('Wishlist', backref='user', uselist=False)
    skin_profile = db.relationship('UserSkinProfile', backref='user', uselist=False,
                                   cascade='all, delete-orphan')
    addresses   = db.relationship('Address', backref='user', lazy='dynamic',
                                  cascade='all, delete-orphan')

    TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

    def get_id(self):
        return str(self.user_id)

    @staticmethod
    def _token_serializer():
        return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='auth-token')

    def generate_token(self):
        """Create a signed, stateless token identifying this user (for API clients
        that can't rely on cookies, e.g. cross-origin or mobile)."""
        return User._token_serializer().dumps({'user_id': self.user_id})

    @staticmethod
    def verify_token(token):
        try:
            data = User._token_serializer().loads(token, max_age=User.TOKEN_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return None
        return User.query.get(data.get('user_id'))

    def set_password(self, plain):
        self.password = bcrypt.generate_password_hash(plain).decode('utf-8')

    def check_password(self, plain):
        return bcrypt.check_password_hash(self.password, plain)

    def has_role(self, role_name):
        return self.roles.filter_by(role_name=role_name).first() is not None

    def is_admin(self):
        return self.has_role('Admin')

    def default_address(self):
        return (self.addresses.filter_by(is_default=True).first()
                or self.addresses.first())

    def order_stats(self):
        """Lifetime figures for the admin customer page. Cancelled orders are
        excluded from spend so the number matches what was actually charged."""
        from sqlalchemy import func as _func
        billable = self.orders.filter(Order.status != 'Cancelled')
        total = db.session.query(_func.coalesce(_func.sum(Order.total_amount), 0))                           .filter(Order.user_id == self.user_id,
                                  Order.status != 'Cancelled').scalar() or 0
        count = billable.count()
        last = self.orders.order_by(Order.created_at.desc()).first()
        return {
            'order_count': count,
            'total_spent': round(float(total), 2),
            'average_order': round(float(total) / count, 2) if count else 0.0,
            'last_order_date': last.created_at.isoformat() if last and last.created_at else None,
        }

    def to_dict(self, include_stats=False):
        data = {
            'user_id': self.user_id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'is_active': self.is_active,
            'roles': [r.role_name for r in self.roles],
            'skin_profile': self.skin_profile.to_dict() if self.skin_profile else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_stats:
            data['stats'] = self.order_stats()
        return data

    def __repr__(self):
        return f'<User {self.email}>'


# ─── 2. Roles ──────────────────────────────────────────────────────────────────
class Role(db.Model):
    __tablename__ = 'roles'
    role_id   = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False)  # Admin, Customer, Staff

    def to_dict(self):
        return {'role_id': self.role_id, 'role_name': self.role_name}

    def __repr__(self):
        return f'<Role {self.role_name}>'


# ─── 3. Brands ─────────────────────────────────────────────────────────────────
class Brand(db.Model):
    __tablename__ = 'brands'
    brand_id    = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(120), unique=True, nullable=False)
    slug        = db.Column(db.String(140), unique=True, nullable=False)
    logo        = db.Column(db.String(300))
    description = db.Column(db.Text)
    country     = db.Column(db.String(80))
    is_active   = db.Column(db.Boolean, default=True, nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship('Product', backref='brand', lazy='dynamic')

    def to_dict(self):
        return {
            'brand_id': self.brand_id,
            'name': self.name,
            'slug': self.slug,
            'logo': self.logo,
            'description': self.description,
            'country': self.country,
            'is_active': self.is_active,
            'product_count': self.products.count(),
        }

    def __repr__(self):
        return f'<Brand {self.name}>'


# ─── 4. Categories ─────────────────────────────────────────────────────────────
class Category(db.Model):
    __tablename__ = 'categories'
    category_id = db.Column(db.Integer, primary_key=True)
    parent_id   = db.Column(db.Integer, db.ForeignKey('categories.category_id'), nullable=True)
    name        = db.Column(db.String(100), nullable=False)
    slug        = db.Column(db.String(140), unique=True, nullable=False)
    description = db.Column(db.Text)
    image       = db.Column(db.String(300))
    sort_order  = db.Column(db.Integer, default=0, nullable=False)

    products = db.relationship('Product', backref='category', lazy='dynamic')
    children = db.relationship('Category', backref=db.backref('parent', remote_side=[category_id]),
                               lazy='dynamic')

    def descendant_ids(self):
        """This category's id plus every id beneath it — lets a parent category
        page ('Cleansers') list products filed under its children."""
        ids = [self.category_id]
        for child in self.children:
            ids.extend(child.descendant_ids())
        return ids

    def breadcrumb(self):
        trail, node = [], self
        while node:
            trail.insert(0, node)
            node = node.parent
        return trail

    def to_dict(self, include_children=False):
        data = {
            'category_id': self.category_id,
            'parent_id': self.parent_id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'image': self.image,
            'sort_order': self.sort_order,
        }
        if include_children:
            data['children'] = [c.to_dict() for c in self.children]
        return data

    def __repr__(self):
        return f'<Category {self.name}>'


# ─── 5. Skin Types ─────────────────────────────────────────────────────────────
class SkinType(db.Model):
    __tablename__ = 'skin_types'
    skin_type_id = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(50), unique=True, nullable=False)  # Oily, Dry, …
    slug         = db.Column(db.String(60), unique=True, nullable=False)
    description  = db.Column(db.Text)
    icon         = db.Column(db.String(20))

    products = db.relationship('Product', secondary='product_skin_types',
                               back_populates='skin_types', lazy='dynamic')

    def to_dict(self):
        return {
            'skin_type_id': self.skin_type_id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'icon': self.icon,
        }

    def __repr__(self):
        return f'<SkinType {self.name}>'


# ─── 6. Skin Concerns ──────────────────────────────────────────────────────────
class SkinConcern(db.Model):
    __tablename__ = 'skin_concerns'
    concern_id  = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(80), unique=True, nullable=False)  # Acne, Dark Spots, …
    slug        = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    icon        = db.Column(db.String(20))

    products = db.relationship('Product', secondary='product_concerns',
                               back_populates='concerns', lazy='dynamic')

    def to_dict(self):
        return {
            'concern_id': self.concern_id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'icon': self.icon,
        }

    def __repr__(self):
        return f'<SkinConcern {self.name}>'


# ─── 7. Ingredients ────────────────────────────────────────────────────────────
class Ingredient(db.Model):
    __tablename__ = 'ingredients'
    ingredient_id = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), unique=True, nullable=False)   # Niacinamide
    inci_name     = db.Column(db.String(200))                                # official INCI name
    slug          = db.Column(db.String(140), unique=True, nullable=False)
    description   = db.Column(db.Text)
    benefits      = db.Column(db.Text)
    is_active_ingredient = db.Column(db.Boolean, default=True, nullable=False)
    # Actives that shouldn't be layered together (retinol + AHA, etc.)
    caution_note  = db.Column(db.Text)

    product_links = db.relationship('ProductIngredient', backref='ingredient',
                                    lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'ingredient_id': self.ingredient_id,
            'name': self.name,
            'inci_name': self.inci_name,
            'slug': self.slug,
            'description': self.description,
            'benefits': self.benefits,
            'is_active_ingredient': self.is_active_ingredient,
            'caution_note': self.caution_note,
        }

    def __repr__(self):
        return f'<Ingredient {self.name}>'


# ─── 8. Product ↔ Ingredient (association object, carries concentration) ───────
class ProductIngredient(db.Model):
    __tablename__ = 'product_ingredients'
    id            = db.Column(db.Integer, primary_key=True)
    product_id    = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredients.ingredient_id'), nullable=False)
    concentration = db.Column(db.String(30))   # '10%', '0.5%', None when undisclosed
    is_key        = db.Column(db.Boolean, default=False, nullable=False)  # hero ingredient
    __table_args__ = (db.UniqueConstraint('product_id', 'ingredient_id', name='uq_product_ingredient'),)

    def to_dict(self):
        return {
            'ingredient_id': self.ingredient_id,
            'name': self.ingredient.name,
            'inci_name': self.ingredient.inci_name,
            'concentration': self.concentration,
            'is_key': self.is_key,
        }


# ─── 9. Products ───────────────────────────────────────────────────────────────
class Product(db.Model):
    __tablename__ = 'products'
    product_id  = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'), nullable=False)
    brand_id    = db.Column(db.Integer, db.ForeignKey('brands.brand_id'), nullable=True)
    name        = db.Column(db.String(200), nullable=False)
    slug        = db.Column(db.String(240), unique=True, nullable=False)
    description = db.Column(db.Text)
    base_price  = db.Column(db.Numeric(10, 2), nullable=False)

    # ── Skincare-specific ──
    product_type    = db.Column(db.String(50))    # Cleanser, Serum, Sunscreen, …
    routine_step    = db.Column(db.Integer)       # 1..6, orders a routine
    texture         = db.Column(db.String(50))    # Gel, Cream, Oil, Foam, Balm
    how_to_use      = db.Column(db.Text)
    ingredients_full = db.Column(db.Text)         # full INCI list
    spf             = db.Column(db.Integer)       # sunscreens only
    pao_months      = db.Column(db.Integer)       # period after opening
    volume_label    = db.Column(db.String(40))    # marketing size, e.g. '50 ml'

    # ── Claim flags (drive the filter chips) ──
    is_vegan               = db.Column(db.Boolean, default=False, nullable=False)
    is_cruelty_free        = db.Column(db.Boolean, default=False, nullable=False)
    is_fragrance_free      = db.Column(db.Boolean, default=False, nullable=False)
    is_non_comedogenic     = db.Column(db.Boolean, default=False, nullable=False)
    is_dermatologist_tested = db.Column(db.Boolean, default=False, nullable=False)
    is_active              = db.Column(db.Boolean, default=True, nullable=False)

    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    PRODUCT_TYPES = [
        'Cleanser', 'Toner', 'Essence', 'Serum', 'Ampoule', 'Moisturizer',
        'Eye Cream', 'Sunscreen', 'Mask', 'Exfoliant', 'Face Oil', 'Mist',
        'Lip Care', 'Spot Treatment',
    ]
    TEXTURES = ['Gel', 'Cream', 'Lotion', 'Foam', 'Oil', 'Balm', 'Water', 'Serum', 'Powder']
    ROUTINE_STEPS = {
        1: 'Cleanse', 2: 'Tone', 3: 'Treat', 4: 'Moisturize', 5: 'Protect', 6: 'Weekly Treatment',
    }

    # Relationships
    variants     = db.relationship('ProductVariant', backref='product', lazy='dynamic',
                                   cascade='all, delete-orphan')
    images       = db.relationship('ProductImage', backref='product', lazy='dynamic',
                                   cascade='all, delete-orphan',
                                   order_by='ProductImage.sort_order')
    reviews      = db.relationship('Review', backref='product', lazy='dynamic')
    promotions   = db.relationship('Promotion', secondary='product_promotions',
                                   backref='products', lazy='dynamic')
    skin_types   = db.relationship('SkinType', secondary='product_skin_types',
                                   back_populates='products', lazy='dynamic')
    concerns     = db.relationship('SkinConcern', secondary='product_concerns',
                                   back_populates='products', lazy='dynamic')
    ingredient_links = db.relationship('ProductIngredient', backref='product',
                                       lazy='dynamic', cascade='all, delete-orphan')

    def avg_rating(self):
        reviews = self.reviews.all()
        if not reviews:
            return 0
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

    def total_stock(self):
        return sum(v.stock for v in self.variants)

    def key_ingredients(self):
        return [link for link in self.ingredient_links.filter_by(is_key=True)]

    def routine_step_label(self):
        return self.ROUTINE_STEPS.get(self.routine_step)

    def claims(self):
        """The claim flags that are true, as display labels."""
        labels = [
            (self.is_vegan, 'Vegan'),
            (self.is_cruelty_free, 'Cruelty-Free'),
            (self.is_fragrance_free, 'Fragrance-Free'),
            (self.is_non_comedogenic, 'Non-Comedogenic'),
            (self.is_dermatologist_tested, 'Dermatologist-Tested'),
        ]
        return [label for flag, label in labels if flag]

    def primary_image_url(self):
        """Gallery image first, then any variant photo as a fallback."""
        primary = self.images.filter_by(is_primary=True).first() or self.images.first()
        if primary:
            return primary.url_absolute()
        first = self.variants.first()
        return first.image_url() if first else None

    def gallery_urls(self):
        urls = [img.url_absolute() for img in self.images]
        if not urls:
            urls = [v.image_url() for v in self.variants if v.image]
        return [u for u in urls if u]

    def to_dict(self, include_variants=True, include_detail=False):
        data = {
            'product_id': self.product_id,
            'category_id': self.category_id,
            'category': self.category.name if self.category else None,
            'brand_id': self.brand_id,
            'brand': self.brand.name if self.brand else None,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'base_price': float(self.base_price),
            'product_type': self.product_type,
            'routine_step': self.routine_step,
            'routine_step_label': self.routine_step_label(),
            'texture': self.texture,
            'spf': self.spf,
            'pao_months': self.pao_months,
            'volume_label': self.volume_label,
            'claims': self.claims(),
            'skin_types': [s.name for s in self.skin_types],
            'concerns': [c.name for c in self.concerns],
            'key_ingredients': [link.to_dict() for link in self.key_ingredients()],
            'image': self.primary_image_url(),
            'images': self.gallery_urls(),
            'avg_rating': self.avg_rating(),
            'review_count': self.reviews.count(),
            'total_stock': self.total_stock(),
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_detail:
            data['how_to_use'] = self.how_to_use
            data['ingredients_full'] = self.ingredients_full
            data['ingredients'] = [link.to_dict() for link in self.ingredient_links]
        if include_variants:
            data['variants'] = [v.to_dict() for v in self.variants]
        return data

    def __repr__(self):
        return f'<Product {self.name}>'


# ─── 10. Product Images ────────────────────────────────────────────────────────
class ProductImage(db.Model):
    __tablename__ = 'product_images'
    image_id   = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    url        = db.Column(db.String(300), nullable=False)
    alt_text   = db.Column(db.String(200))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)

    def url_absolute(self):
        """Same resolution rule as ProductVariant.image_url() — stored value is
        either a /static-relative path or a full external URL."""
        if not self.url:
            return None
        if self.url.startswith('http://') or self.url.startswith('https://'):
            return self.url
        from flask import url_for
        return url_for('static', filename=self.url, _external=True)

    def to_dict(self):
        return {
            'image_id': self.image_id,
            'product_id': self.product_id,
            'url': self.url_absolute(),
            'alt_text': self.alt_text,
            'sort_order': self.sort_order,
            'is_primary': self.is_primary,
        }


# ─── 11. Product Variants ──────────────────────────────────────────────────────
class ProductVariant(db.Model):
    __tablename__ = 'product_variants'
    variant_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    sku        = db.Column(db.String(60), unique=True)
    volume     = db.Column(db.String(50))    # '50 ml', '100 ml', 'Travel 15 ml'
    shade      = db.Column(db.String(50))    # tinted SPF / BB only, usually NULL
    price      = db.Column(db.Numeric(10, 2), nullable=False)
    compare_at_price = db.Column(db.Numeric(10, 2))   # strike-through "was" price
    stock      = db.Column(db.Integer, default=0, nullable=False)
    weight_grams = db.Column(db.Integer)     # shipping weight
    batch_no   = db.Column(db.String(60))
    expiry_date = db.Column(db.Date)
    image      = db.Column(db.String(300))

    # Relationships
    cart_items     = db.relationship('CartItem', backref='variant', lazy='dynamic')
    order_items    = db.relationship('OrderItem', backref='variant', lazy='dynamic')
    inventory_logs = db.relationship('InventoryLog', backref='variant', lazy='dynamic')
    stock_alerts   = db.relationship('BackInStockAlert', backref='variant', lazy='dynamic',
                                     cascade='all, delete-orphan')

    def label(self):
        parts = [p for p in (self.volume, self.shade) if p]
        return ' / '.join(parts) or 'Standard'

    def is_on_sale(self):
        return bool(self.compare_at_price and
                    float(self.compare_at_price) > float(self.price))

    def discount_percent(self):
        if not self.is_on_sale():
            return 0
        was, now = float(self.compare_at_price), float(self.price)
        return int(round((was - now) / was * 100))

    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < datetime.utcnow().date())

    def days_until_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - datetime.utcnow().date()).days

    def image_url(self):
        """Resolve the stored image reference to an absolute URL.

        `image` holds either a path relative to /static (e.g. 'images/foo.jpg',
        as used by seeded local product photos) or a full external URL (as
        entered via the admin "Image URL" field). Building an absolute URL
        here — rather than storing one — keeps it correct across hosts
        (localhost, prod domain, ngrok) and lets cross-origin frontends load it.
        """
        if not self.image:
            return self.product.primary_image_url() if self.product else None
        if self.image.startswith('http://') or self.image.startswith('https://'):
            return self.image
        from flask import url_for
        return url_for('static', filename=self.image, _external=True)

    def to_dict(self):
        return {
            'variant_id': self.variant_id,
            'product_id': self.product_id,
            'sku': self.sku,
            'volume': self.volume,
            'shade': self.shade,
            'label': self.label(),
            'price': float(self.price),
            'compare_at_price': float(self.compare_at_price) if self.compare_at_price else None,
            'is_on_sale': self.is_on_sale(),
            'discount_percent': self.discount_percent(),
            'stock': self.stock,
            'weight_grams': self.weight_grams,
            'batch_no': self.batch_no,
            'expiry_date': self.expiry_date.isoformat() if self.expiry_date else None,
            'image': self.image_url(),
        }

    def __repr__(self):
        return f'<Variant {self.product_id} {self.label()}>'


# ─── 12. User Skin Profile ─────────────────────────────────────────────────────
class UserSkinProfile(db.Model):
    __tablename__ = 'user_skin_profiles'
    profile_id   = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.user_id'),
                             nullable=False, unique=True)
    skin_type_id = db.Column(db.Integer, db.ForeignKey('skin_types.skin_type_id'), nullable=True)
    age_range    = db.Column(db.String(20))    # '18-24', '25-34', …
    skin_tone    = db.Column(db.String(30))    # Fair, Light, Medium, Tan, Deep
    is_sensitive = db.Column(db.Boolean, default=False, nullable=False)
    allergies    = db.Column(db.Text)          # free text: 'fragrance, essential oils'
    notes        = db.Column(db.Text)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    skin_type = db.relationship('SkinType')
    concerns  = db.relationship('SkinConcern', secondary='skin_profile_concerns', lazy='dynamic')

    AGE_RANGES  = ['Under 18', '18-24', '25-34', '35-44', '45-54', '55+']
    SKIN_TONES  = ['Fair', 'Light', 'Medium', 'Tan', 'Deep']

    def to_dict(self):
        return {
            'profile_id': self.profile_id,
            'user_id': self.user_id,
            'skin_type_id': self.skin_type_id,
            'skin_type': self.skin_type.name if self.skin_type else None,
            'age_range': self.age_range,
            'skin_tone': self.skin_tone,
            'is_sensitive': self.is_sensitive,
            'allergies': self.allergies,
            'notes': self.notes,
            'concerns': [c.name for c in self.concerns],
            'concern_ids': [c.concern_id for c in self.concerns],
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ─── 13. Addresses ─────────────────────────────────────────────────────────────
class Address(db.Model):
    __tablename__ = 'addresses'
    address_id     = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    label          = db.Column(db.String(40), default='Home')   # Home, Work, …
    recipient_name = db.Column(db.String(120), nullable=False)
    phone          = db.Column(db.String(20), nullable=False)
    line1          = db.Column(db.String(200), nullable=False)
    line2          = db.Column(db.String(200))
    city           = db.Column(db.String(100), nullable=False)
    state          = db.Column(db.String(100))
    postal_code    = db.Column(db.String(20))
    country        = db.Column(db.String(80), default='Cambodia', nullable=False)
    is_default     = db.Column(db.Boolean, default=False, nullable=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    def one_line(self):
        parts = [self.line1, self.line2, self.city, self.state, self.postal_code, self.country]
        return ', '.join(p for p in parts if p)

    def to_dict(self):
        return {
            'address_id': self.address_id,
            'user_id': self.user_id,
            'label': self.label,
            'recipient_name': self.recipient_name,
            'phone': self.phone,
            'line1': self.line1,
            'line2': self.line2,
            'city': self.city,
            'state': self.state,
            'postal_code': self.postal_code,
            'country': self.country,
            'is_default': self.is_default,
            'one_line': self.one_line(),
        }


# ─── 14. Wishlist ──────────────────────────────────────────────────────────────
class Wishlist(db.Model):
    __tablename__ = 'wishlists'
    wishlist_id = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.user_id'),
                            nullable=False, unique=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    items       = db.relationship('WishlistItem', backref='wishlist', lazy='dynamic',
                                  cascade='all, delete-orphan')

    def item_count(self):
        return self.items.count()

    def has_product(self, product_id):
        return self.items.filter_by(product_id=product_id).first() is not None

    def to_dict(self):
        return {
            'wishlist_id': self.wishlist_id,
            'user_id': self.user_id,
            'items': [i.to_dict() for i in self.items],
            'item_count': self.item_count(),
        }


class WishlistItem(db.Model):
    __tablename__ = 'wishlist_items'
    wishlist_item_id = db.Column(db.Integer, primary_key=True)
    wishlist_id      = db.Column(db.Integer, db.ForeignKey('wishlists.wishlist_id'), nullable=False)
    product_id       = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__   = (db.UniqueConstraint('wishlist_id', 'product_id', name='uq_wishlist_product'),)

    product = db.relationship('Product')

    def to_dict(self):
        return {
            'wishlist_item_id': self.wishlist_item_id,
            'product_id': self.product_id,
            'product': self.product.to_dict(include_variants=False),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ─── 15. Bundles / Routine Kits ────────────────────────────────────────────────
class Bundle(db.Model):
    __tablename__ = 'bundles'
    bundle_id   = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(160), nullable=False)
    slug        = db.Column(db.String(200), unique=True, nullable=False)
    description = db.Column(db.Text)
    image       = db.Column(db.String(300))
    price       = db.Column(db.Numeric(10, 2), nullable=False)
    is_active   = db.Column(db.Boolean, default=True, nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('BundleItem', backref='bundle', lazy='dynamic',
                            cascade='all, delete-orphan')

    def items_total(self):
        """What the contents would cost bought separately."""
        return sum(float(i.variant.price) * i.quantity for i in self.items)

    def savings(self):
        return max(0.0, round(self.items_total() - float(self.price), 2))

    def in_stock(self):
        return all(i.variant.stock >= i.quantity for i in self.items)

    def image_absolute(self):
        if not self.image:
            first = self.items.first()
            return first.variant.image_url() if first else None
        if self.image.startswith('http://') or self.image.startswith('https://'):
            return self.image
        from flask import url_for
        return url_for('static', filename=self.image, _external=True)

    def to_dict(self):
        return {
            'bundle_id': self.bundle_id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'image': self.image_absolute(),
            'price': float(self.price),
            'items_total': round(self.items_total(), 2),
            'savings': self.savings(),
            'in_stock': self.in_stock(),
            'is_active': self.is_active,
            'items': [i.to_dict() for i in self.items],
        }


class BundleItem(db.Model):
    __tablename__ = 'bundle_items'
    bundle_item_id = db.Column(db.Integer, primary_key=True)
    bundle_id      = db.Column(db.Integer, db.ForeignKey('bundles.bundle_id'), nullable=False)
    variant_id     = db.Column(db.Integer, db.ForeignKey('product_variants.variant_id'), nullable=False)
    quantity       = db.Column(db.Integer, default=1, nullable=False)

    variant = db.relationship('ProductVariant')

    def to_dict(self):
        return {
            'bundle_item_id': self.bundle_item_id,
            'variant_id': self.variant_id,
            'quantity': self.quantity,
            'product_name': self.variant.product.name,
            'variant': self.variant.to_dict(),
        }


# ─── 16. Cart ──────────────────────────────────────────────────────────────────
class Cart(db.Model):
    __tablename__ = 'carts'
    cart_id    = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items      = db.relationship('CartItem', backref='cart', lazy='dynamic',
                                 cascade='all, delete-orphan')

    def total(self):
        return sum(item.subtotal() for item in self.items)

    def item_count(self):
        return sum(item.quantity for item in self.items)

    def total_weight_grams(self):
        return sum((item.variant.weight_grams or 0) * item.quantity for item in self.items)

    def to_dict(self):
        return {
            'cart_id': self.cart_id,
            'user_id': self.user_id,
            'items': [item.to_dict() for item in self.items],
            'total': self.total(),
            'item_count': self.item_count(),
        }


# ─── 17. Cart Items ────────────────────────────────────────────────────────────
class CartItem(db.Model):
    __tablename__ = 'cart_items'
    cart_item_id = db.Column(db.Integer, primary_key=True)
    cart_id      = db.Column(db.Integer, db.ForeignKey('carts.cart_id'), nullable=False)
    variant_id   = db.Column(db.Integer, db.ForeignKey('product_variants.variant_id'), nullable=False)
    quantity     = db.Column(db.Integer, default=1, nullable=False)

    def subtotal(self):
        return float(self.variant.price) * self.quantity

    def to_dict(self):
        return {
            'cart_item_id': self.cart_item_id,
            'cart_id': self.cart_id,
            'variant_id': self.variant_id,
            'quantity': self.quantity,
            'subtotal': self.subtotal(),
            'variant': self.variant.to_dict(),
            'product_id': self.variant.product_id,
            'product_name': self.variant.product.name,
            'brand_name': self.variant.product.brand.name if self.variant.product.brand else None,
        }


# ─── 18. Coupons ───────────────────────────────────────────────────────────────
class Coupon(db.Model):
    __tablename__ = 'coupons'
    coupon_id      = db.Column(db.Integer, primary_key=True)
    code           = db.Column(db.String(50), unique=True, nullable=False)
    discount_type  = db.Column(db.String(20), nullable=False)   # percentage / fixed
    discount_value = db.Column(db.Numeric(10, 2), nullable=False)
    min_amount     = db.Column(db.Numeric(10, 2), default=0)
    expiry_date    = db.Column(db.DateTime)
    orders         = db.relationship('Order', backref='coupon', lazy='dynamic')

    def is_valid(self):
        if self.expiry_date and self.expiry_date < datetime.utcnow():
            return False
        return True

    def apply(self, amount):
        if not self.is_valid():
            return amount
        if float(amount) < float(self.min_amount):
            return amount
        if self.discount_type == 'percentage':
            return round(float(amount) * (1 - float(self.discount_value) / 100), 2)
        return max(0, float(amount) - float(self.discount_value))

    def to_dict(self):
        return {
            'coupon_id': self.coupon_id,
            'code': self.code,
            'discount_type': self.discount_type,
            'discount_value': float(self.discount_value),
            'min_amount': float(self.min_amount),
            'expiry_date': self.expiry_date.isoformat() if self.expiry_date else None,
            'is_valid': self.is_valid(),
        }


# ─── 19. Shipping Methods ──────────────────────────────────────────────────────
class ShippingMethod(db.Model):
    __tablename__ = 'shipping_methods'
    method_id     = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(80), nullable=False)     # Standard, Express
    description   = db.Column(db.String(200))
    fee           = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    free_over     = db.Column(db.Numeric(10, 2))   # free shipping threshold
    eta_days_min  = db.Column(db.Integer, default=2, nullable=False)
    eta_days_max  = db.Column(db.Integer, default=5, nullable=False)
    is_active     = db.Column(db.Boolean, default=True, nullable=False)
    sort_order    = db.Column(db.Integer, default=0, nullable=False)

    orders = db.relationship('Order', backref='shipping_method', lazy='dynamic')

    def fee_for(self, subtotal):
        if self.free_over is not None and float(subtotal) >= float(self.free_over):
            return 0.0
        return float(self.fee)

    def eta_label(self):
        if self.eta_days_min == self.eta_days_max:
            return f'{self.eta_days_min} day{"s" if self.eta_days_min != 1 else ""}'
        return f'{self.eta_days_min}–{self.eta_days_max} days'

    def to_dict(self, subtotal=None):
        return {
            'method_id': self.method_id,
            'name': self.name,
            'description': self.description,
            'fee': float(self.fee),
            'free_over': float(self.free_over) if self.free_over is not None else None,
            'fee_for_cart': self.fee_for(subtotal) if subtotal is not None else None,
            'eta_days_min': self.eta_days_min,
            'eta_days_max': self.eta_days_max,
            'eta_label': self.eta_label(),
            'is_active': self.is_active,
        }


# ─── 20. Orders ────────────────────────────────────────────────────────────────
class Order(db.Model):
    __tablename__ = 'orders'
    order_id     = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    coupon_id    = db.Column(db.Integer, db.ForeignKey('coupons.coupon_id'), nullable=True)
    shipping_method_id = db.Column(db.Integer, db.ForeignKey('shipping_methods.method_id'),
                                   nullable=True)

    # Money breakdown — total_amount is the charged figure; the rest reconciles it.
    subtotal        = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    discount_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    shipping_fee    = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    tax             = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    total_amount    = db.Column(db.Numeric(10, 2), nullable=False)

    status       = db.Column(db.String(50), default='Pending')
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    items          = db.relationship('OrderItem', backref='order', lazy='dynamic',
                                     cascade='all, delete-orphan')
    payment        = db.relationship('Payment', backref='order', uselist=False)
    shipping       = db.relationship('Shipping', backref='order', uselist=False)
    status_history = db.relationship('OrderStatusHistory', backref='order', lazy='dynamic',
                                     cascade='all, delete-orphan',
                                     order_by='OrderStatusHistory.created_at')
    returns        = db.relationship('ReturnRequest', backref='order', lazy='dynamic')

    STATUS_CHOICES = ['Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled']

    def set_status(self, new_status, note=None, changed_by=None):
        """Change status and record it in the history trail."""
        if new_status == self.status:
            return None
        entry = OrderStatusHistory(
            order_id     = self.order_id,
            from_status  = self.status,
            to_status    = new_status,
            note         = note,
            changed_by_user_id = changed_by,
        )
        self.status = new_status
        db.session.add(entry)
        return entry

    def item_count(self):
        return sum(i.quantity for i in self.items)

    def to_dict(self, include_items=True):
        data = {
            'order_id': self.order_id,
            'user_id': self.user_id,
            'coupon_id': self.coupon_id,
            'shipping_method_id': self.shipping_method_id,
            'shipping_method': self.shipping_method.name if self.shipping_method else None,
            'subtotal': float(self.subtotal or 0),
            'discount_amount': float(self.discount_amount or 0),
            'shipping_fee': float(self.shipping_fee or 0),
            'tax': float(self.tax or 0),
            'total_amount': float(self.total_amount),
            'status': self.status,
            'item_count': self.item_count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'payment': self.payment.to_dict() if self.payment else None,
            'shipping': self.shipping.to_dict() if self.shipping else None,
            'status_history': [h.to_dict() for h in self.status_history],
        }
        if include_items:
            data['items'] = [item.to_dict() for item in self.items]
        return data


# ─── 21. Order Items ───────────────────────────────────────────────────────────
class OrderItem(db.Model):
    __tablename__ = 'order_items'
    order_item_id = db.Column(db.Integer, primary_key=True)
    order_id      = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)
    variant_id    = db.Column(db.Integer, db.ForeignKey('product_variants.variant_id'), nullable=False)
    quantity      = db.Column(db.Integer, nullable=False)
    price         = db.Column(db.Numeric(10, 2), nullable=False)  # price at time of order
    # Snapshots — a product can be renamed or deleted after the order is placed.
    product_name  = db.Column(db.String(220))
    variant_label = db.Column(db.String(120))

    def subtotal(self):
        return float(self.price) * self.quantity

    def returned_quantity(self):
        return sum(ri.quantity for ri in self.return_items
                   if ri.return_request.status in ('Approved', 'Received', 'Refunded'))

    def to_dict(self):
        return {
            'order_item_id': self.order_item_id,
            'order_id': self.order_id,
            'variant_id': self.variant_id,
            'quantity': self.quantity,
            'price': float(self.price),
            'subtotal': self.subtotal(),
            'product_name': self.product_name or (self.variant.product.name if self.variant else None),
            'variant_label': self.variant_label or (self.variant.label() if self.variant else None),
            'variant': self.variant.to_dict() if self.variant else None,
        }


# ─── 22. Order Status History ──────────────────────────────────────────────────
class OrderStatusHistory(db.Model):
    __tablename__ = 'order_status_history'
    history_id  = db.Column(db.Integer, primary_key=True)
    order_id    = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)
    from_status = db.Column(db.String(50))
    to_status   = db.Column(db.String(50), nullable=False)
    note        = db.Column(db.String(300))
    changed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    changed_by = db.relationship('User')

    def to_dict(self):
        return {
            'history_id': self.history_id,
            'order_id': self.order_id,
            'from_status': self.from_status,
            'to_status': self.to_status,
            'note': self.note,
            'changed_by': self.changed_by.name if self.changed_by else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ─── 23. Payments ──────────────────────────────────────────────────────────────
class Payment(db.Model):
    __tablename__ = 'payments'
    payment_id = db.Column(db.Integer, primary_key=True)
    order_id   = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False, unique=True)
    method     = db.Column(db.String(50))   # Credit Card, Cash, KHQR, etc.
    amount     = db.Column(db.Numeric(10, 2), nullable=False)
    status     = db.Column(db.String(50), default='Pending')   # Pending, Paid, Failed, Refunded
    paid_at    = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'payment_id': self.payment_id,
            'order_id': self.order_id,
            'method': self.method,
            'amount': float(self.amount),
            'status': self.status,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
        }


# ─── 24. Shipping ──────────────────────────────────────────────────────────────
class Shipping(db.Model):
    __tablename__ = 'shipping'
    shipping_id = db.Column(db.Integer, primary_key=True)
    order_id    = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False, unique=True)
    recipient_name = db.Column(db.String(120))
    address     = db.Column(db.String(300), nullable=False)
    city        = db.Column(db.String(100), nullable=False)
    postal_code = db.Column(db.String(20))
    country     = db.Column(db.String(80))
    phone       = db.Column(db.String(20), nullable=False)
    status      = db.Column(db.String(50), default='Preparing')  # Preparing, Shipped, Delivered
    tracking_number = db.Column(db.String(80))
    carrier     = db.Column(db.String(80))
    shipped_at  = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'shipping_id': self.shipping_id,
            'order_id': self.order_id,
            'recipient_name': self.recipient_name,
            'address': self.address,
            'city': self.city,
            'postal_code': self.postal_code,
            'country': self.country,
            'phone': self.phone,
            'status': self.status,
            'tracking_number': self.tracking_number,
            'carrier': self.carrier,
            'shipped_at': self.shipped_at.isoformat() if self.shipped_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None,
        }


# ─── 25. Reviews ───────────────────────────────────────────────────────────────
class Review(db.Model):
    __tablename__ = 'reviews'
    review_id  = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    rating     = db.Column(db.Integer, nullable=False)   # 1–5
    title      = db.Column(db.String(160))
    comment    = db.Column(db.Text)
    # Skincare reviews are only useful when you know whose skin it's on.
    skin_type_id = db.Column(db.Integer, db.ForeignKey('skin_types.skin_type_id'), nullable=True)
    age_range    = db.Column(db.String(20))
    is_verified_purchase = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    skin_type = db.relationship('SkinType')

    def to_dict(self):
        return {
            'review_id': self.review_id,
            'user_id': self.user_id,
            'product_id': self.product_id,
            'rating': self.rating,
            'title': self.title,
            'comment': self.comment,
            'skin_type': self.skin_type.name if self.skin_type else None,
            'age_range': self.age_range,
            'is_verified_purchase': self.is_verified_purchase,
            'user_name': self.user.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ─── 26. Promotions ────────────────────────────────────────────────────────────
class Promotion(db.Model):
    __tablename__ = 'promotions'
    promotion_id     = db.Column(db.Integer, primary_key=True)
    name             = db.Column(db.String(150), nullable=False)
    discount_percent = db.Column(db.Numeric(5, 2), nullable=False)
    start_date       = db.Column(db.DateTime, nullable=False)
    end_date         = db.Column(db.DateTime, nullable=False)

    def is_active(self):
        now = datetime.utcnow()
        return self.start_date <= now <= self.end_date

    def to_dict(self):
        return {
            'promotion_id': self.promotion_id,
            'name': self.name,
            'discount_percent': float(self.discount_percent),
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'is_active': self.is_active(),
            'product_ids': [p.product_id for p in self.products],
        }


# ─── 27. Inventory Logs ────────────────────────────────────────────────────────
class InventoryLog(db.Model):
    __tablename__ = 'inventory_logs'
    log_id      = db.Column(db.Integer, primary_key=True)
    variant_id  = db.Column(db.Integer, db.ForeignKey('product_variants.variant_id'), nullable=False)
    change_type = db.Column(db.String(20), nullable=False)   # IN, OUT, ADJUSTMENT
    quantity    = db.Column(db.Integer, nullable=False)
    reference   = db.Column(db.String(200))   # order_id, restock note, etc.
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'log_id': self.log_id,
            'variant_id': self.variant_id,
            'change_type': self.change_type,
            'quantity': self.quantity,
            'reference': self.reference,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ─── 28. Back-in-Stock Alerts ──────────────────────────────────────────────────
class BackInStockAlert(db.Model):
    __tablename__ = 'back_in_stock_alerts'
    alert_id    = db.Column(db.Integer, primary_key=True)
    variant_id  = db.Column(db.Integer, db.ForeignKey('product_variants.variant_id'), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True)
    email       = db.Column(db.String(180), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    notified_at = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('variant_id', 'email', name='uq_alert_variant_email'),)

    user = db.relationship('User', backref='stock_alerts')

    def to_dict(self):
        return {
            'alert_id': self.alert_id,
            'variant_id': self.variant_id,
            'user_id': self.user_id,
            'email': self.email,
            'product_name': self.variant.product.name if self.variant else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'notified_at': self.notified_at.isoformat() if self.notified_at else None,
        }


# ─── 29. Returns ───────────────────────────────────────────────────────────────
class ReturnRequest(db.Model):
    __tablename__ = 'return_requests'
    return_id     = db.Column(db.Integer, primary_key=True)
    order_id      = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    status        = db.Column(db.String(30), default='Requested', nullable=False)
    reason        = db.Column(db.String(80))    # Reaction, Wrong item, Damaged, …
    details       = db.Column(db.Text)
    refund_amount = db.Column(db.Numeric(10, 2))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at   = db.Column(db.DateTime)

    user  = db.relationship('User', backref='returns')
    items = db.relationship('ReturnItem', backref='return_request', lazy='dynamic',
                            cascade='all, delete-orphan')

    STATUS_CHOICES = ['Requested', 'Approved', 'Rejected', 'Received', 'Refunded']
    # Skin reactions are the #1 return reason in skincare — track it explicitly
    # so the catalog team can spot a problem SKU.
    REASONS = ['Skin reaction / irritation', 'Wrong item received', 'Damaged on arrival',
               'Expired or near expiry', 'Not as described', 'Changed my mind']

    def requested_total(self):
        return sum(float(i.order_item.price) * i.quantity for i in self.items)

    def to_dict(self):
        return {
            'return_id': self.return_id,
            'order_id': self.order_id,
            'user_id': self.user_id,
            'user_name': self.user.name if self.user else None,
            'status': self.status,
            'reason': self.reason,
            'details': self.details,
            'refund_amount': float(self.refund_amount) if self.refund_amount is not None else None,
            'requested_total': round(self.requested_total(), 2),
            'items': [i.to_dict() for i in self.items],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
        }


class ReturnItem(db.Model):
    __tablename__ = 'return_items'
    return_item_id = db.Column(db.Integer, primary_key=True)
    return_id      = db.Column(db.Integer, db.ForeignKey('return_requests.return_id'), nullable=False)
    order_item_id  = db.Column(db.Integer, db.ForeignKey('order_items.order_item_id'), nullable=False)
    quantity       = db.Column(db.Integer, default=1, nullable=False)

    order_item = db.relationship('OrderItem', backref='return_items')

    def to_dict(self):
        return {
            'return_item_id': self.return_item_id,
            'order_item_id': self.order_item_id,
            'quantity': self.quantity,
            'product_name': self.order_item.product_name,
            'price': float(self.order_item.price),
        }


# ─── 30. Subscriptions (replenishment) ─────────────────────────────────────────
class Subscription(db.Model):
    """Recurring refill of a single variant.

    This stores the schedule only — creating the actual repeat orders needs a
    scheduled job that scans for `next_delivery_at <= today` and status Active.
    """
    __tablename__ = 'subscriptions'
    subscription_id = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    variant_id    = db.Column(db.Integer, db.ForeignKey('product_variants.variant_id'), nullable=False)
    address_id    = db.Column(db.Integer, db.ForeignKey('addresses.address_id'), nullable=True)
    quantity      = db.Column(db.Integer, default=1, nullable=False)
    interval_days = db.Column(db.Integer, default=30, nullable=False)
    discount_percent = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    status        = db.Column(db.String(20), default='Active', nullable=False)
    next_delivery_at = db.Column(db.DateTime)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    cancelled_at  = db.Column(db.DateTime)

    user    = db.relationship('User', backref='subscriptions')
    variant = db.relationship('ProductVariant', backref='subscriptions')
    address = db.relationship('Address')

    STATUS_CHOICES = ['Active', 'Paused', 'Cancelled']
    INTERVALS = {30: 'Every month', 60: 'Every 2 months', 90: 'Every 3 months'}

    def interval_label(self):
        return self.INTERVALS.get(self.interval_days, f'Every {self.interval_days} days')

    def unit_price(self):
        price = float(self.variant.price)
        return round(price * (1 - float(self.discount_percent) / 100), 2)

    def to_dict(self):
        return {
            'subscription_id': self.subscription_id,
            'user_id': self.user_id,
            'variant_id': self.variant_id,
            'address_id': self.address_id,
            'quantity': self.quantity,
            'interval_days': self.interval_days,
            'interval_label': self.interval_label(),
            'discount_percent': float(self.discount_percent),
            'unit_price': self.unit_price(),
            'status': self.status,
            'product_name': self.variant.product.name if self.variant else None,
            'variant': self.variant.to_dict() if self.variant else None,
            'next_delivery_at': self.next_delivery_at.isoformat() if self.next_delivery_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ─── 31. Bakong Merchant ───────────────────────────────────────────────────────
class BakongMerchant(db.Model):
    __tablename__ = 'bakong_merchants'
    merchant_id     = db.Column(db.Integer, primary_key=True)
    merchant_name   = db.Column(db.String(100), nullable=False)
    bank_account    = db.Column(db.String(50), nullable=False)
    merchant_city   = db.Column(db.String(50), nullable=False)
    terminal_label  = db.Column(db.String(50), nullable=False)
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'merchant_id': self.merchant_id,
            'merchant_name': self.merchant_name,
            'bank_account': self.bank_account,
            'merchant_city': self.merchant_city,
            'terminal_label': self.terminal_label,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<BakongMerchant {self.merchant_name}>'


# ─── 32. Payment Transactions ──────────────────────────────────────────────────
class PaymentTransaction(db.Model):
    __tablename__ = 'payment_transactions'
    transaction_id = db.Column(db.Integer, primary_key=True)
    qr_string      = db.Column(db.Text, nullable=False)
    md5_hash       = db.Column(db.String(32), nullable=False, unique=True)
    amount         = db.Column(db.Numeric(10, 2), nullable=False)
    currency       = db.Column(db.String(3), default='KHR')
    user_id        = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    order_id       = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=True)
    status         = db.Column(db.String(20), default='Pending')  # Pending, Paid, Failed, Expired
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at        = db.Column(db.DateTime)

    # Relationships
    user = db.relationship('User', backref='payment_transactions')
    order = db.relationship('Order', backref='payment_transaction')

    def to_dict(self):
        return {
            'transaction_id': self.transaction_id,
            'md5_hash': self.md5_hash,
            'amount': float(self.amount),
            'currency': self.currency,
            'user_id': self.user_id,
            'order_id': self.order_id,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
        }

    def __repr__(self):
        return f'<PaymentTransaction {self.transaction_id} {self.status}>'
