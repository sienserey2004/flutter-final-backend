from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from flask_bcrypt import Bcrypt

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


# ─── 1. Users ──────────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    user_id    = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False)
    email      = db.Column(db.String(180), unique=True, nullable=False)
    password   = db.Column(db.String(256), nullable=False)
    phone      = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    roles      = db.relationship('Role', secondary='user_roles', backref='users', lazy='dynamic')
    orders     = db.relationship('Order', backref='user', lazy='dynamic')
    reviews    = db.relationship('Review', backref='user', lazy='dynamic')
    cart       = db.relationship('Cart', backref='user', uselist=False)

    def get_id(self):
        return str(self.user_id)

    def set_password(self, plain):
        self.password = bcrypt.generate_password_hash(plain).decode('utf-8')

    def check_password(self, plain):
        return bcrypt.check_password_hash(self.password, plain)

    def has_role(self, role_name):
        return self.roles.filter_by(role_name=role_name).first() is not None

    def is_admin(self):
        return self.has_role('Admin')

    def __repr__(self):
        return f'<User {self.email}>'


# ─── 2. Roles ──────────────────────────────────────────────────────────────────
class Role(db.Model):
    __tablename__ = 'roles'
    role_id   = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(50), unique=True, nullable=False)  # Admin, Customer, Staff

    def __repr__(self):
        return f'<Role {self.role_name}>'


# ─── 4. Categories ─────────────────────────────────────────────────────────────
class Category(db.Model):
    __tablename__ = 'categories'
    category_id = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    products    = db.relationship('Product', backref='category', lazy='dynamic')

    def __repr__(self):
        return f'<Category {self.name}>'


# ─── 5. Products ───────────────────────────────────────────────────────────────
class Product(db.Model):
    __tablename__ = 'products'
    product_id  = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'), nullable=False)
    name        = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    base_price  = db.Column(db.Numeric(10, 2), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    variants    = db.relationship('ProductVariant', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    reviews     = db.relationship('Review', backref='product', lazy='dynamic')
    promotions  = db.relationship('Promotion', secondary='product_promotions', backref='products', lazy='dynamic')

    def avg_rating(self):
        reviews = self.reviews.all()
        if not reviews:
            return 0
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

    def total_stock(self):
        return sum(v.stock for v in self.variants)

    def __repr__(self):
        return f'<Product {self.name}>'


# ─── 6. Product Variants ───────────────────────────────────────────────────────
class ProductVariant(db.Model):
    __tablename__ = 'product_variants'
    variant_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    size       = db.Column(db.String(50))
    color      = db.Column(db.String(50))
    price      = db.Column(db.Numeric(10, 2), nullable=False)
    stock      = db.Column(db.Integer, default=0, nullable=False)
    image      = db.Column(db.String(300))

    # Relationships
    cart_items     = db.relationship('CartItem', backref='variant', lazy='dynamic')
    order_items    = db.relationship('OrderItem', backref='variant', lazy='dynamic')
    inventory_logs = db.relationship('InventoryLog', backref='variant', lazy='dynamic')

    def __repr__(self):
        return f'<Variant {self.product_id} {self.size}/{self.color}>'


# ─── 7. Cart ───────────────────────────────────────────────────────────────────
class Cart(db.Model):
    __tablename__ = 'carts'
    cart_id    = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items      = db.relationship('CartItem', backref='cart', lazy='dynamic', cascade='all, delete-orphan')

    def total(self):
        return sum(item.subtotal() for item in self.items)

    def item_count(self):
        return sum(item.quantity for item in self.items)


# ─── 8. Cart Items ─────────────────────────────────────────────────────────────
class CartItem(db.Model):
    __tablename__ = 'cart_items'
    cart_item_id = db.Column(db.Integer, primary_key=True)
    cart_id      = db.Column(db.Integer, db.ForeignKey('carts.cart_id'), nullable=False)
    variant_id   = db.Column(db.Integer, db.ForeignKey('product_variants.variant_id'), nullable=False)
    quantity     = db.Column(db.Integer, default=1, nullable=False)

    def subtotal(self):
        return float(self.variant.price) * self.quantity


# ─── 14. Coupons ───────────────────────────────────────────────────────────────
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


# ─── 9. Orders ─────────────────────────────────────────────────────────────────
class Order(db.Model):
    __tablename__ = 'orders'
    order_id     = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    coupon_id    = db.Column(db.Integer, db.ForeignKey('coupons.coupon_id'), nullable=True)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    status       = db.Column(db.String(50), default='Pending')  # Pending, Processing, Shipped, Delivered, Cancelled
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    items    = db.relationship('OrderItem', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    payment  = db.relationship('Payment', backref='order', uselist=False)
    shipping = db.relationship('Shipping', backref='order', uselist=False)

    STATUS_CHOICES = ['Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled']


# ─── 10. Order Items ───────────────────────────────────────────────────────────
class OrderItem(db.Model):
    __tablename__ = 'order_items'
    order_item_id = db.Column(db.Integer, primary_key=True)
    order_id      = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False)
    variant_id    = db.Column(db.Integer, db.ForeignKey('product_variants.variant_id'), nullable=False)
    quantity      = db.Column(db.Integer, nullable=False)
    price         = db.Column(db.Numeric(10, 2), nullable=False)  # price at time of order

    def subtotal(self):
        return float(self.price) * self.quantity


# ─── 11. Payments ──────────────────────────────────────────────────────────────
class Payment(db.Model):
    __tablename__ = 'payments'
    payment_id = db.Column(db.Integer, primary_key=True)
    order_id   = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False, unique=True)
    method     = db.Column(db.String(50))   # Credit Card, Cash, PayPal, etc.
    amount     = db.Column(db.Numeric(10, 2), nullable=False)
    status     = db.Column(db.String(50), default='Pending')   # Pending, Paid, Failed, Refunded
    paid_at    = db.Column(db.DateTime)


# ─── 12. Shipping ──────────────────────────────────────────────────────────────
class Shipping(db.Model):
    __tablename__ = 'shipping'
    shipping_id = db.Column(db.Integer, primary_key=True)
    order_id    = db.Column(db.Integer, db.ForeignKey('orders.order_id'), nullable=False, unique=True)
    address     = db.Column(db.String(300), nullable=False)
    city        = db.Column(db.String(100), nullable=False)
    phone       = db.Column(db.String(20), nullable=False)
    status      = db.Column(db.String(50), default='Preparing')  # Preparing, Shipped, Delivered


# ─── 13. Reviews ───────────────────────────────────────────────────────────────
class Review(db.Model):
    __tablename__ = 'reviews'
    review_id  = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    rating     = db.Column(db.Integer, nullable=False)   # 1–5
    comment    = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─── 15. Promotions ────────────────────────────────────────────────────────────
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


# ─── 17. Inventory Logs ────────────────────────────────────────────────────────
class InventoryLog(db.Model):
    __tablename__ = 'inventory_logs'
    log_id      = db.Column(db.Integer, primary_key=True)
    variant_id  = db.Column(db.Integer, db.ForeignKey('product_variants.variant_id'), nullable=False)
    change_type = db.Column(db.String(20), nullable=False)   # IN, OUT, ADJUSTMENT
    quantity    = db.Column(db.Integer, nullable=False)
    reference   = db.Column(db.String(200))   # order_id, restock note, etc.
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


# ─── 18. Bakong Merchant ───────────────────────────────────────────────────────
class BakongMerchant(db.Model):
    __tablename__ = 'bakong_merchants'
    merchant_id     = db.Column(db.Integer, primary_key=True)
    merchant_name   = db.Column(db.String(100), nullable=False)
    bank_account    = db.Column(db.String(50), nullable=False)
    merchant_city   = db.Column(db.String(50), nullable=False)
    terminal_label  = db.Column(db.String(50), nullable=False)
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<BakongMerchant {self.merchant_name}>'


# ─── 19. Payment Transactions ──────────────────────────────────────────────────
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

    def __repr__(self):
        return f'<PaymentTransaction {self.transaction_id} {self.status}>'
