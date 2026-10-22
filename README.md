# 🌿 Aurea Skin — Skincare E-Commerce Backend

A Flask backend that serves **two front ends from one codebase**: a server-rendered
storefront + admin panel for the browser, and a **JSON REST API** for the Flutter
mobile app.

Every route answers in the caller's language. `GET /products/` renders an HTML
page; `GET /api/products/` returns the same data as JSON. One set of business
rules, no duplicated logic, no drift between web and mobile.

**Interactive API docs: [`/api/docs`](http://localhost:5000/api/docs)** (Swagger UI) ·
spec at [`/api/openapi.json`](http://localhost:5000/api/openapi.json)

---

## Tech Stack

| Layer     | Technology                                          |
|-----------|-----------------------------------------------------|
| Backend   | Flask 3.0, Flask-Login, Flask-Migrate, Flask-CORS   |
| ORM       | SQLAlchemy 2.0 + psycopg2 (PostgreSQL) / SQLite     |
| API docs  | OpenAPI 3.0.3 + Swagger UI                          |
| Templates | Jinja2 + Bootstrap 5 + Bootstrap Icons              |
| Admin UI  | AdminLTE 4                                          |
| Auth      | Flask-Bcrypt · session cookies (web) + JWT bearer tokens (mobile) |
| Payments  | Bakong KHQR (Cambodian QR payment)                  |
| Images    | Pillow                                              |

---

## Quick Start

```bash
pip install -r requirements.txt

# No DATABASE_URL? It falls back to SQLite at instance/ecommerce.db —
# nothing to install, good enough to run and demo.
python seed.py        # drops, recreates and fills the database
python run.py         # http://localhost:5000
```

For PostgreSQL, put the URL in `.env`:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/py_ecommerce
SECRET_KEY=change-me-to-a-long-random-string
FLASK_ENV=development
```

The app creates the database and tables on first boot if they don't exist, and
adds any column a newer release introduced.

### Seeded accounts

| Role     | Email             | Password   |
|----------|-------------------|------------|
| Admin    | admin@shop.com    | `admin123` |
| Customer | alice@example.com | `password` |
| Customer | bob@example.com   | `password` |
| Customer | maya@example.com  | `password` |

### Seeded coupons

| Code      | Type       | Value | Minimum order |
|-----------|------------|-------|---------------|
| WELCOME10 | percentage | 10%   | $0            |
| GLOW20    | percentage | 20%   | $80           |
| FLAT15    | fixed      | $15   | $60           |

---

## The API

### How dual-format routing works

Every blueprint is registered twice — once bare, once under `/api`:

```python
app.register_blueprint(products_bp, url_prefix='/products')
app.register_blueprint(products_bp, url_prefix='/api/products', name='api_products')
```

`wants_json()` in [`app/api.py`](app/api.py) decides the format. Anything under
`/api/` is always JSON. Elsewhere it follows `?format=json`, a JSON request body,
or the `Accept` header — with a deliberate exception: browsers send
`Sec-Fetch-Mode: navigate` on real page loads, so a form submit never gets JSON
back even when its `Accept` header is a bare `*/*`.

### Response envelope

```json
{ "success": true,  "data": { ... } }
{ "success": false, "error": "Not found" }
```

A `422` also carries `errors`, one message per failed field:

```json
{ "success": false, "error": "Validation failed",
  "errors": ["Email is required.", "Password must be at least 6 characters."] }
```

### Authentication

`POST /api/auth/login` returns a stateless **JWT** (HS256). Send it on every
later request:

```
Authorization: Bearer <token>
```

Valid for 30 days. It stops working the moment an admin deactivates the account —
the flag is re-checked on each request, not just at login. Browsers may use the
session cookie instead; both are accepted.

```bash
TOKEN=$(curl -s -X POST localhost:5000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@example.com","password":"password"}' | jq -r .token)

curl -s localhost:5000/api/cart/ -H "Authorization: Bearer $TOKEN"
```

### Status codes

| Code | Meaning                                              |
|------|------------------------------------------------------|
| 200  | OK                                                   |
| 201  | Created                                              |
| 400  | Malformed request                                    |
| 401  | No or invalid token                                  |
| 403  | Signed in but not allowed (admin-only, or suspended) |
| 404  | No such resource                                     |
| 405  | Wrong method for that path                           |
| 409  | Conflict — stock ran out mid-checkout                |
| 413  | Upload over the 5 MB limit                           |
| 422  | Validation failed — see `errors`                     |
| 500  | Unexpected server error                              |

**Errors are always JSON for API clients — never an HTML page.** Every handler
lives in [`app/__init__.py`](app/__init__.py) and branches on `wants_json()`.

### Endpoint map

Full reference with request/response schemas at **`/api/docs`**. In brief:

| Group      | Endpoints |
|------------|-----------|
| Auth       | `POST /api/auth/register` · `POST /api/auth/login` · `GET /api/auth/logout` · `GET\|POST /api/auth/profile` |
| Catalog    | `GET /api/` (home feed) · `GET /api/products/` (search + 14 filters) · `GET /api/products/{id}` · `/api/products/for-you` · `/brand/{slug}` · `/concern/{slug}` · `/ingredient/{slug}` · `/bundles` · `GET /api/ingredients` |
| Categories | `GET /api/categories/` (tree, `?flat=1`) · `GET /api/categories/{id\|slug}` · `GET /api/categories/{id\|slug}/products` |
| Cart       | `GET /api/cart/` · `POST /api/cart/add` · `/add-bundle` · `/update/{id}` · `/remove/{id}` · `/clear` |
| Orders     | `GET /api/orders/` · `GET /api/orders/{id}` · `GET\|POST /api/orders/checkout` · `/khqr-payment/{tx}` · `POST /api/orders/api/check-payment` |
| Account    | `/api/account/` · `/skin-profile` · `/addresses` (CRUD) · `/wishlist` + `/wishlist/toggle` · `/alerts` · `/subscriptions` · `/returns` |
| Reviews    | `POST /api/reviews/submit` · `POST /api/reviews/{id}/delete` |
| Admin      | `/api/admin/users` · `/api/admin/categories` · `/api/admin/products` · `/api/admin/orders` · `/api/admin/inventory` · `/api/admin/coupons` · … |

Categories accept **either an id or a slug** — `/api/categories/3` and
`/api/categories/cleansers` return the same thing. A parent category rolls up
everything filed under its children.

---

## Database

40 tables. The nine entities the brief asks for, plus what a real skincare
catalogue needs (variants, ingredients, skin types, concerns, subscriptions,
returns).

```
Users ──< User_Roles >── Roles
  │
  ├──< Addresses
  ├──< Orders ──< Order_Items >── Product_Variants ──< Products
  │      ├── Payments · Shipping · Order_Status_History
  │      └── Coupons · Shipping_Methods
  ├──  Cart ──< Cart_Items >── Product_Variants
  ├──  Wishlist ──< Wishlist_Items >── Products
  ├──  User_Skin_Profile ──< Skin_Profile_Concerns >── Skin_Concerns
  ├──< Reviews ── Products
  ├──< Subscriptions · Return_Requests ──< Return_Items
  └──< Back_In_Stock_Alerts

Products ──< Product_Images
         ──< Product_Variants ──< Inventory_Logs
         ──< Product_Ingredients >── Ingredients
         ──< Product_Skin_Types >── Skin_Types
         ──< Product_Concerns   >── Skin_Concerns
         ──< Product_Promotions >── Promotions
         ──  Categories (self-referencing parent/child)
         ──  Brands

Bundles ──< Bundle_Items >── Product_Variants
Bakong_Merchants · Payment_Transactions
```

Every model has a `to_dict()` — that's the single source of truth for the JSON
shape, so the API and the templates can never disagree about a field.

Key design choices:

- **Categories self-reference** (`parent_id`) for a real hierarchy. `descendant_ids()`
  makes a parent category list everything beneath it.
- **Variants hold price and stock**, not products. A 30 ml and a 50 ml bottle are
  different SKUs at different prices.
- **Order items snapshot** `product_name`, `variant_label` and `price` at purchase
  time, so renaming or deleting a product never rewrites order history.
- **Users are deactivated, not deleted**, once they have orders — order history is
  a financial record.

---

## Features

### Storefront
- Home feed: new arrivals, bestsellers, on-sale, categories, concerns, bundles
- Catalogue with 14 filters — search, category, brand, skin type, concern,
  ingredient, product type, routine step, price range, SPF, in-stock, on-sale,
  and five ethical claims — plus five sort orders and pagination
- Category browser with hierarchy and live product counts
- Product detail: gallery, variant picker, INCI list, ingredient explainers,
  reviews filterable by the reviewer's skin type
- Ingredient glossary
- "For you" recommendations matched to the saved skin profile

### Cart & checkout
- Per-variant cart with stock clamping and out-of-stock warnings
- Routine kits explode into individual lines so one item can still be dropped
- Coupons (percentage and fixed) with minimum-order rules
- Selectable delivery methods with live re-quoting
- Saved addresses or a one-off address at checkout
- Five payment methods, including **Bakong KHQR** with auto-polling
- Stock is re-checked at the last moment before the order is written

### Account
- Register / login / logout, profile editing
- Skin profile (type, age range, concerns) driving recommendations
- Address book with a default address
- Wishlist / favourites
- Back-in-stock alerts, refill subscriptions, return requests

### Admin panel (`/admin`)
- Dashboard: revenue, orders, low stock, expiring stock, monthly series
- **Customer management** — search and filter by role or status, customer
  detail with lifetime spend, order history, reviews, addresses and wishlist;
  create, edit, reset password, promote/demote, suspend/restore, delete
- Full CRUD: categories (hierarchical), brands, products, variants, images,
  ingredients, bundles, coupons, promotions, shipping methods
- Order pipeline: Pending → Processing → Shipped → Delivered / Cancelled, with
  tracking numbers and status history
- Inventory with low-stock and expiry warnings; returns; stock-alert mailbox
- Bakong merchant config and payment transaction log

**Guardrails.** You can't demote, suspend or delete your own account, can't
remove the last active admin, and can't delete a customer who has placed an
order — the API returns `422` with the reason, and the buttons are disabled in
the UI.

---

## Project Structure

```
backend/
├── app/
│   ├── __init__.py           # App factory, blueprints, error handlers
│   ├── api.py                # wants_json() + the JSON envelope helpers
│   ├── docs.py               # OpenAPI 3.0 spec + Swagger UI
│   ├── models.py             # 40 tables, each with to_dict()
│   ├── utils.py              # slugify / unique_slug
│   ├── routes/
│   │   ├── main.py           # Home feed, ingredient glossary
│   │   ├── auth.py           # Register / login / logout / profile
│   │   ├── products.py       # Catalogue, filters, detail, bundles
│   │   ├── categories.py     # Category tree and category browsing
│   │   ├── cart.py           # Cart operations
│   │   ├── orders.py         # Checkout, history, KHQR payment
│   │   ├── account.py        # Addresses, wishlist, skin profile, returns
│   │   ├── reviews.py        # Review submission
│   │   └── admin.py          # Admin panel — all CRUD
│   ├── static/css/main.css   # Design system (CSS custom properties)
│   └── templates/
│       ├── base.html, error.html, 403.html, 404.html
│       ├── main/ auth/ products/ cart/ orders/ account/
│       └── admin/            # 37 AdminLTE templates
├── migrations/versions/      # Alembic
├── config.py                 # Dev / prod config
├── run.py                    # WSGI entry point
├── manage.py                 # Flask CLI commands
├── seed.py                   # Sample catalogue, users, orders
├── Dockerfile
└── requirements.txt
```

---

## Design System

Driven by CSS custom properties in [`app/static/css/main.css`](app/static/css/main.css):

| Token             | Value      | Use                        |
|-------------------|------------|----------------------------|
| `--c-primary`     | `#3c4c33`  | Deep olive — buttons, links |
| `--c-primary-lt`  | `#e8eeda`  | Soft sage — surfaces        |
| `--c-bg`          | `#f4e8d6`  | Warm sand background        |
| `--c-text`        | `#25301f`  | Near-black green            |
| `--font-display`  | Figtree    | Headings and UI             |
| `--font-serif`    | Instrument Serif | Editorial accents     |
| `--font-mono`     | DM Mono    | Prices, SKUs, numerics      |

---

## CLI Commands

```bash
python seed.py              # Rebuild and seed the whole database
flask create-admin          # Create an admin account interactively
flask seed-db               # Same as seed.py, via the CLI
flask db migrate -m "msg"   # Generate an Alembic migration
flask db upgrade            # Apply pending migrations
```

---

## Deployment

`Dockerfile` and `gunicorn` are included:

```bash
docker build -t aurea-skin .
docker run -p 5000:5000 --env-file .env aurea-skin
```

Behind a proxy, `ProxyFix` reads `X-Forwarded-*` so redirects and URLs use the
external scheme and host. CORS is open (`*`) because the mobile app authenticates
with a bearer token rather than cookies — no credentials cross origins.
