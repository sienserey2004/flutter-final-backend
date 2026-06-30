# 🌿 FreshMart — Fresh Fruit E-Commerce

A full-stack e-commerce application built with **Flask**, **Jinja2**, **Bootstrap 5**, and **PostgreSQL**, designed for fresh fruit and produce online stores.

**Theme:** Fresh, organic, and inviting UI — warm cream background, leaf-green accents, citrus-orange CTAs, rounded cards, and a Nunito typeface for a friendly, natural feel.

---

## Tech Stack

| Layer       | Technology                                        |
|-------------|---------------------------------------------------|
| Backend     | Flask 3.0, Flask-Login, Flask-Migrate             |
| ORM         | SQLAlchemy 2.0 + psycopg2-binary                  |
| Templates   | Jinja2 + Bootstrap 5.3.3 + Bootstrap Icons 1.11.3 |
| Styling     | Custom CSS design system (Nunito + DM Mono fonts) |
| Database    | PostgreSQL 15+                                    |
| Auth        | Flask-Login + Flask-Bcrypt (session-based)        |
| Forms       | Flask-WTF + WTForms + email-validator             |
| Payments    | Bakong KHQR (Cambodian QR payment)                |
| Images      | Pillow (image processing)                         |

---

## Project Structure

```
ecommerce/
├── app/
│   ├── __init__.py              # App factory, extensions, blueprints
│   ├── models.py                # 17 SQLAlchemy ORM models
│   ├── routes/
│   │   ├── main.py              # Homepage (hero, categories, featured products)
│   │   ├── auth.py              # Login / register / logout / profile
│   │   ├── products.py          # Product listing, search, filter, detail
│   │   ├── cart.py              # Cart add / update / remove / clear
│   │   ├── orders.py            # Checkout, order history, KHQR payment
│   │   ├── reviews.py           # Product review submission
│   │   └── admin.py             # Full admin panel (all CRUD)
│   ├── static/
│   │   └── css/
│   │       └── main.css         # Fresh fruit design system (CSS variables)
│   └── templates/
│       ├── base.html            # Base layout — navbar + dark-green footer
│       ├── main/
│       │   └── index.html       # Homepage — hero, features, categories, CTA
│       ├── auth/
│       │   ├── login.html       # Sign-in page
│       │   ├── register.html    # Account creation
│       │   └── profile.html     # Profile edit
│       ├── products/
│       │   ├── list.html        # Product listing with sidebar filters
│       │   ├── detail.html      # Product page — gallery, variants, reviews
│       │   └── _card.html       # Reusable product card component
│       ├── cart/
│       │   └── cart.html        # Cart with image rows + order summary
│       ├── orders/
│       │   ├── checkout.html    # Shipping + payment form
│       │   ├── list.html        # Order history (desktop table + mobile cards)
│       │   ├── detail.html      # Order detail — items, shipping, payment
│       │   └── khqr_payment.html# KHQR QR-code payment page
│       ├── admin/               # Full admin panel (18 templates)
│       ├── 403.html
│       └── 404.html
├── config.py                    # Dev / prod configuration classes
├── run.py                       # WSGI entry point
├── manage.py                    # CLI commands
├── seed.py                      # Database seeder (sample products & users)
├── requirements.txt
└── .env
```

---

## Database Schema (17 Tables)

```
Users ───< User_Roles >─── Roles
Users ───< Orders ───< Order_Items >─── Product_Variants ─── Products ─── Categories
           │                                    │
           │                                    └── Inventory_Logs
           ├── Payments  (method, status, KHQR md5_hash)
           ├── Shipping  (address, city, phone, status)
           └── Coupons   (percentage / fixed, expiry)
Users ── Reviews ─── Products
Users ── Cart ───< Cart_Items >─── Product_Variants
Products ───< Product_Promotions >─── Promotions
Bakong_Merchants (KHQR merchant config)
Payment_Transactions (KHQR transaction log)
```

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- PostgreSQL 15+ running on port **5433**
- Database: `py_ecommerce`, user: `myuser`, password: `MySecretPassword`

### 2. Install dependencies

```bash
cd ecommerce
pip install -r requirements.txt
```

### 3. Configure environment

Create or verify `.env` in the project root:

```env
DATABASE_URL=postgresql+psycopg2://myuser:MySecretPassword@localhost:5433/py_ecommerce
SECRET_KEY=change-me-to-a-long-random-string
FLASK_ENV=development
```

### 4. Set up the database

```bash
# Option A — seed script (drops & recreates all tables + inserts sample data)
python seed.py

# Option B — Flask-Migrate (incremental, production-friendly)
flask db init
flask db migrate -m "initial schema"
flask db upgrade
flask create-admin
```

### 5. Run the app

```bash
python run.py
# or
flask run --port 5000
```

Open **http://localhost:5000**

---

## Sample Credentials (after seeding)

| Role     | Email               | Password   |
|----------|---------------------|------------|
| Admin    | admin@shop.com      | admin123   |
| Customer | alice@example.com   | password   |
| Customer | bob@example.com     | password   |

---

## Sample Coupon Codes

| Code       | Type       | Value | Min Order |
|------------|------------|-------|-----------|
| WELCOME10  | percentage | 10%   | $0        |
| SAVE20     | percentage | 20%   | $100      |
| FLAT15     | fixed      | $15   | $50       |

---

## Features

### Storefront
- Homepage with animated hero, features strip ("Organic / Fast Delivery / Quality Checked"), category pills, featured product grid, and a CTA section
- Product listing with sidebar filters — search, category, sort (newest / price ↑↓), pagination
- Product detail with image gallery, variant selector (size/color), live price update, quantity stepper, and promotion badges
- Star ratings + verified review submission
- Related products section

### Cart & Checkout
- Image-first cart rows with inline quantity stepper and per-item remove
- Checkout with shipping form + five payment methods (Cash on Delivery, Credit Card, PayPal, Bank Transfer, KHQR)
- Coupon code application (percentage and fixed discounts)
- KHQR / Bakong QR payment with 60-second auto-polling and deep-link to Bakong app

### Account
- Register / Login / Logout with remember-me option
- Profile editing — name, phone, password
- Order history (responsive desktop table + mobile card layout)
- Order detail — line items, shipping address, payment status

### Admin Panel (`/admin`)
- Dashboard — total users, products, orders, revenue; order status breakdown; quick-action links
- Full CRUD for Categories, Products, and Product Variants (with image URLs)
- Order management with status pipeline: Pending → Processing → Shipped → Delivered → Cancelled
- Coupon management — percentage and fixed types, expiry dates, minimum order amounts
- Promotion campaigns — date-bounded, applied per product
- Inventory log — all IN / OUT / ADJUSTMENT entries with timestamps
- User list with Admin role toggle
- Bakong merchant configuration (KHQR API key, merchant ID)
- Payment transaction history

---

## Design System

The entire UI is driven by CSS variables defined in `app/static/css/main.css`:

| Token              | Value       | Use                         |
|--------------------|-------------|-----------------------------|
| `--c-primary`      | `#2a7d4f`   | Leaf green — buttons, links |
| `--c-orange`       | `#e0611a`   | Citrus — Add to Cart CTA    |
| `--c-yellow`       | `--f0b429`  | Star ratings, promo badges  |
| `--c-bg`           | `#fdfbf5`   | Warm cream body background  |
| `--c-text`         | `#1a2412`   | Dark forest text            |
| `--radius-xl`      | `22px`      | Cards, auth boxes           |
| Font (heading/body)| Nunito      | Round, friendly weight 700–800 |
| Font (prices/codes)| DM Mono     | Monospace numerics          |

---

## CLI Commands

```bash
flask create-admin          # Interactive admin account creation
flask seed-db               # Re-seed sample categories, products, users
flask db migrate -m "msg"   # Generate a new Alembic migration
flask db upgrade            # Apply pending migrations
```
# flask-pro-ecom
