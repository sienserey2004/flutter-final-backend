"""
seed.py — populate the database with sample data for development.
Run: python seed.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from run import app
from app.models import (
    db, User, Role, UserRole, Category, Product, ProductVariant,
    Cart, Coupon, Promotion, ProductPromotion
)
from datetime import datetime, timedelta


def seed():
    with app.app_context():
        print("Dropping and recreating tables…")
        db.drop_all()
        db.create_all()

        # ── Roles ──────────────────────────────────────────────────────────────
        admin_role    = Role(role_name='Admin')
        customer_role = Role(role_name='Customer')
        staff_role    = Role(role_name='Staff')
        db.session.add_all([admin_role, customer_role, staff_role])
        db.session.flush()

        # ── Users ──────────────────────────────────────────────────────────────
        admin = User(name='Admin User', email='admin@shop.com', phone='+1 555 0100')
        admin.set_password('admin123')
        admin.roles.append(admin_role)
        admin.roles.append(customer_role)

        alice = User(name='Alice Johnson', email='alice@example.com', phone='+1 555 0101')
        alice.set_password('password')
        alice.roles.append(customer_role)

        bob = User(name='Bob Smith', email='bob@example.com', phone='+1 555 0102')
        bob.set_password('password')
        bob.roles.append(customer_role)

        db.session.add_all([admin, alice, bob])
        db.session.flush()

        # Carts
        for u in [admin, alice, bob]:
            db.session.add(Cart(user_id=u.user_id))

        # ── Categories ─────────────────────────────────────────────────────────
        cats = {
            'Apparel':       'Clothing and fashion items',
            'Electronics':   'Gadgets and tech accessories',
            'Home & Living': 'Furniture and home decor',
            'Books':         'Printed and digital books',
            'Sports':        'Sports and outdoor equipment',
        }
        cat_objs = {}
        for name, desc in cats.items():
            c = Category(name=name, description=desc)
            db.session.add(c)
            cat_objs[name] = c
        db.session.flush()

        # ── Products & Variants ─────────────────────────────────────────────────
        product_data = [
            # (name, category, description, base_price, variants)
            # variants: [(size, color, price, stock, image_url)]
            ('Classic Cotton Tee', 'Apparel',
             'A timeless cotton tee cut for everyday wear. Pre-shrunk, lightweight, and breathable.',
             29.99,
             [('S', 'White', 29.99, 50, 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=600'),
              ('M', 'White', 29.99, 80, 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=600'),
              ('L', 'Black', 29.99, 60, 'https://images.unsplash.com/photo-1503341733017-1901578f9f1e?w=600'),
              ('XL','Black', 29.99, 30, 'https://images.unsplash.com/photo-1503341733017-1901578f9f1e?w=600')]),

            ('Slim Fit Chinos', 'Apparel',
             'Modern slim-fit chinos in a stretch-cotton blend. Goes from office to weekend effortlessly.',
             79.99,
             [('30', 'Navy',  79.99, 25, 'https://images.unsplash.com/photo-1542272604-787c3835535d?w=600'),
              ('32', 'Navy',  79.99, 30, 'https://images.unsplash.com/photo-1542272604-787c3835535d?w=600'),
              ('32', 'Khaki', 79.99, 20, 'https://images.unsplash.com/photo-1473966968600-fa801b869a1a?w=600'),
              ('34', 'Khaki', 84.99, 15, 'https://images.unsplash.com/photo-1473966968600-fa801b869a1a?w=600')]),

            ('Wireless Earbuds Pro', 'Electronics',
             'True wireless earbuds with active noise cancellation, 30-hour battery, and IPX5 water resistance.',
             149.99,
             [(None, 'Black', 149.99, 40, 'https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=600'),
              (None, 'White', 149.99, 35, 'https://images.unsplash.com/photo-1631176093617-910e84a84bca?w=600')]),

            ('Mechanical Keyboard', 'Electronics',
             'Compact TKL mechanical keyboard with RGB backlight and tactile brown switches.',
             129.99,
             [(None, 'Black', 129.99, 20, 'https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=600'),
              (None, 'Silver',139.99, 15, 'https://images.unsplash.com/photo-1595225476474-8a4b3735bec3?w=600')]),

            ('Minimalist Desk Lamp', 'Home & Living',
             'Touch-controlled LED lamp with 3 brightness levels and a USB-A charging port built in.',
             59.99,
             [(None, 'White', 59.99, 45, 'https://images.unsplash.com/photo-1507473885765-e6ed057f782c?w=600'),
              (None, 'Black', 59.99, 30, 'https://images.unsplash.com/photo-1534073737927-85f1ebff1f5d?w=600')]),

            ('Ceramic Pour-Over Set', 'Home & Living',
             'Hand-thrown ceramic dripper, server, and two cups. For the coffee ritual enthusiast.',
             89.99,
             [(None, 'Matte White', 89.99, 18, 'https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=600'),
              (None, 'Sage Green', 94.99, 12, 'https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=600')]),

            ('The Design of Everyday Things', 'Books',
             'Don Norman\'s classic on user-centred design. Required reading for designers and makers.',
             24.99,
             [(None, None, 24.99, 100, 'https://images.unsplash.com/photo-1544947950-fa07a98d237f?w=600')]),

            ('Atomic Habits', 'Books',
             'James Clear\'s #1 bestseller on building good habits and breaking bad ones.',
             19.99,
             [(None, None, 19.99, 120, 'https://images.unsplash.com/photo-1512820790803-83ca734da794?w=600')]),

            ('Yoga Mat Pro', 'Sports',
             '6mm non-slip natural rubber yoga mat with alignment lines. Includes carry strap.',
             65.00,
             [(None, 'Slate Grey', 65.00, 35, 'https://images.unsplash.com/photo-1601925228008-6e6e2e1aec9b?w=600'),
              (None, 'Dusty Rose', 65.00, 28, 'https://images.unsplash.com/photo-1601925228008-6e6e2e1aec9b?w=600')]),

            ('Running Shoes X2', 'Sports',
             'Lightweight daily trainer with responsive foam midsole and breathable mesh upper.',
             119.99,
             [('7',  'Black/White', 119.99, 12, 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600'),
              ('8',  'Black/White', 119.99, 18, 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600'),
              ('9',  'Navy/Grey',   124.99, 14, 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600'),
              ('10', 'Navy/Grey',   124.99, 10, 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600')]),
        ]

        product_objs = []
        for name, cat_name, desc, price, variants in product_data:
            p = Product(
                category_id = cat_objs[cat_name].category_id,
                name        = name,
                description = desc,
                base_price  = price
            )
            db.session.add(p)
            db.session.flush()
            for size, color, vprice, stock, img in variants:
                v = ProductVariant(
                    product_id = p.product_id,
                    size       = size,
                    color      = color,
                    price      = vprice,
                    stock      = stock,
                    image      = img
                )
                db.session.add(v)
            product_objs.append(p)
        db.session.flush()

        # ── Coupons ────────────────────────────────────────────────────────────
        coupons = [
            Coupon(code='WELCOME10', discount_type='percentage', discount_value=10,
                   min_amount=0,   expiry_date=datetime.utcnow() + timedelta(days=365)),
            Coupon(code='SAVE20',   discount_type='percentage', discount_value=20,
                   min_amount=100, expiry_date=datetime.utcnow() + timedelta(days=180)),
            Coupon(code='FLAT15',   discount_type='fixed',      discount_value=15,
                   min_amount=50,  expiry_date=datetime.utcnow() + timedelta(days=90)),
        ]
        db.session.add_all(coupons)
        db.session.flush()

        # ── Promotions ─────────────────────────────────────────────────────────
        promo = Promotion(
            name             = 'Summer Sale',
            discount_percent = 15,
            start_date       = datetime.utcnow() - timedelta(days=1),
            end_date         = datetime.utcnow() + timedelta(days=30)
        )
        db.session.add(promo)
        db.session.flush()

        # Apply promo to Apparel products
        for p in product_objs:
            if p.category.name == 'Apparel':
                promo.products.append(p)

        db.session.commit()
        print("✓ Seed complete!")
        print(f"  Admin login: admin@shop.com / admin123")
        print(f"  User login:  alice@example.com / password")
        print(f"  Coupons:     WELCOME10, SAVE20, FLAT15")


if __name__ == '__main__':
    seed()
