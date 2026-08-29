from flask import Flask, render_template, redirect, url_for, flash, request
from flask_cors import CORS
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError
from werkzeug.exceptions import HTTPException
from sqlalchemy.pool import StaticPool
from werkzeug.middleware.proxy_fix import ProxyFix
from config import config
from app.models import db, bcrypt, User

login_manager = LoginManager()
migrate = Migrate()


def _create_database_if_not_exists(database_url):
    """Create PostgreSQL database if it doesn't exist (local only)."""
    if 'postgresql' not in database_url:
        return

    from urllib.parse import urlparse
    parsed = urlparse(database_url)

    # Skip for remote/managed databases (Supabase, RDS, etc.) — they already exist
    host = parsed.hostname or ''
    if host not in ('localhost', '127.0.0.1', '::1') and not host.startswith('192.168.'):
        print(f"[db] Remote host detected ({host}), skipping auto-create.")
        return

    db_name = parsed.path.lstrip('/')
    admin_url = database_url.replace(f'/{db_name}', '/postgres')
    if '+' not in admin_url:
        admin_url = admin_url.replace('postgresql://', 'postgresql+psycopg2://', 1)

    try:
        engine = create_engine(admin_url, isolation_level='AUTOCOMMIT',
                               echo=False, poolclass=StaticPool)
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
            if not result.fetchone():
                conn.execute(text(f"CREATE DATABASE {db_name}"))
                print(f"[db] Created database '{db_name}'")
            else:
                print(f"[db] Database '{db_name}' already exists")
        engine.dispose()
    except Exception as e:
        print(f"[db] Warning: Could not auto-create database: {type(e).__name__}: {e}")


# Columns added after the first release. db.create_all() only creates missing
# *tables*, so an existing database needs these filled in by hand (the Alembic
# migration does the same thing for the flask db upgrade path).
_ADDED_COLUMNS = [
    ('users', 'is_active', 'BOOLEAN NOT NULL DEFAULT TRUE'),
]


def _ensure_added_columns():
    """Add any post-release column that's missing from an existing database."""
    inspector = inspect(db.engine)
    for table, column, ddl in _ADDED_COLUMNS:
        try:
            if table not in inspector.get_table_names():
                continue
            existing = {c['name'] for c in inspector.get_columns(table)}
            if column in existing:
                continue
            if db.engine.dialect.name == 'sqlite':
                # SQLite can't add a NOT NULL column without a literal default.
                ddl = ddl.replace('DEFAULT TRUE', 'DEFAULT 1')
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
            print(f"[db] Added missing column {table}.{column}")
        except Exception as e:
            print(f"[db] Could not add {table}.{column}: {type(e).__name__}: {e}")


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Allow any frontend origin to call the API (no cookies/credentials
    # sent cross-origin, so a wildcard origin is safe here).
    CORS(app, resources={r"/*": {"origins": "*"}})

    # Auto-create database if it doesn't exist
    _create_database_if_not_exists(app.config['SQLALCHEMY_DATABASE_URI'])

    # Init extensions
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # Create all tables if they don't exist
    with app.app_context():
        try:
            db.create_all()
            _ensure_added_columns()
            print("[db] Tables created/verified OK")
        except ProgrammingError as e:
            if 'does not exist' in str(e):
                print(f"[db] ERROR: Database does not exist. Create it manually: createdb py_ecommerce")
            else:
                print(f"[db] Note: {e}")
        except Exception as e:
            print(f"[db] Could not create tables: {type(e).__name__}: {e}")

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        user = User.query.get(int(user_id))
        return user if user and user.is_active else None

    @login_manager.request_loader
    def load_user_from_token(req):
        """Fall back to a bearer token when there's no session cookie — lets
        cross-origin/API clients authenticate by storing the token from
        POST /api/auth/login instead of relying on cookies (which CORS here
        doesn't send cross-origin)."""
        auth_header = req.headers.get('Authorization', '')
        token = auth_header[7:].strip() if auth_header.startswith('Bearer ') else None
        if not token:
            token = req.args.get('token')
        if not token:
            return None
        user = User.verify_token(token)
        # A deactivated account keeps a valid signature until the token expires,
        # so the flag has to be re-checked on every request.
        return user if user and user.is_active else None

    @login_manager.unauthorized_handler
    def unauthorized():
        from app.api import wants_json, api_error
        if wants_json():
            return api_error('Authentication required.', 401)
        flash(login_manager.login_message, login_manager.login_message_category)
        return redirect(url_for(login_manager.login_view, next=request.path))

    # Register blueprints
    from app.routes.auth     import auth_bp
    from app.routes.products import products_bp
    from app.routes.cart     import cart_bp
    from app.routes.orders   import orders_bp
    from app.routes.admin    import admin_bp
    from app.routes.reviews  import reviews_bp
    from app.routes.account  import account_bp
    from app.routes.main     import main_bp
    from app.routes.categories import categories_bp
    from app.docs             import docs_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp,     url_prefix='/auth')
    app.register_blueprint(products_bp, url_prefix='/products')
    app.register_blueprint(cart_bp,     url_prefix='/cart')
    app.register_blueprint(orders_bp,   url_prefix='/orders')
    app.register_blueprint(admin_bp,    url_prefix='/admin')
    app.register_blueprint(reviews_bp,  url_prefix='/reviews')
    app.register_blueprint(account_bp,  url_prefix='/account')
    app.register_blueprint(categories_bp, url_prefix='/categories')
    app.register_blueprint(docs_bp)

    # Same blueprints again under /api/* — forces JSON responses (see
    # wants_json() in app/api.py) instead of rendered HTML templates.
    app.register_blueprint(main_bp,     url_prefix='/api',         name='api_main')
    app.register_blueprint(auth_bp,     url_prefix='/api/auth',     name='api_auth')
    app.register_blueprint(products_bp, url_prefix='/api/products', name='api_products')
    app.register_blueprint(cart_bp,     url_prefix='/api/cart',     name='api_cart')
    app.register_blueprint(orders_bp,   url_prefix='/api/orders',   name='api_orders')
    app.register_blueprint(admin_bp,    url_prefix='/api/admin',    name='api_admin')
    app.register_blueprint(reviews_bp,  url_prefix='/api/reviews',  name='api_reviews')
    app.register_blueprint(account_bp,  url_prefix='/api/account',  name='api_account')
    app.register_blueprint(categories_bp, url_prefix='/api/categories', name='api_categories')

    # Jinja2 globals
    from datetime import datetime
    app.jinja_env.globals['now'] = datetime.utcnow
    app.jinja_env.globals['STORE_NAME'] = app.config.get('STORE_NAME', 'Aurea Skin')
    app.jinja_env.globals['STORE_TAGLINE'] = app.config.get('STORE_TAGLINE', '')

    @app.context_processor
    def inject_nav_taxonomies():
        """Categories/concerns for the storefront nav, on every page."""
        from app.models import Category, SkinConcern
        try:
            return {
                'nav_categories': Category.query.filter_by(parent_id=None)
                                          .order_by(Category.sort_order).all(),
                'nav_concerns': SkinConcern.query.order_by(SkinConcern.name).limit(8).all(),
            }
        except Exception:
            # Before the first migration/seed the tables may not exist yet.
            return {'nav_categories': [], 'nav_concerns': []}

    # ── Error handlers ─────────────────────────────────────────────────────────
    # Every handler answers in the caller's language: JSON for API clients,
    # a rendered page for browsers. An API client must never receive HTML.
    from app.api import wants_json, api_error

    @app.errorhandler(400)
    def bad_request(e):
        if wants_json():
            return api_error(getattr(e, 'description', None) or 'Bad request', 400)
        return render_template('error.html', code=400, title='Bad Request',
                               message="That request couldn't be understood."), 400

    @app.errorhandler(403)
    def forbidden(e):
        if wants_json():
            return api_error('Forbidden', 403)
        return render_template('403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        if wants_json():
            return api_error('Not found', 404)
        return render_template('404.html'), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        allowed = sorted(e.valid_methods or []) if hasattr(e, 'valid_methods') else []
        if wants_json():
            return api_error(f'Method {request.method} not allowed for this endpoint.',
                             405, allowed_methods=allowed)
        return render_template('error.html', code=405, title='Method Not Allowed',
                               message='That action isn't available here.'), 405

    @app.errorhandler(413)
    def payload_too_large(e):
        limit_mb = app.config.get('MAX_CONTENT_LENGTH', 0) // (1024 * 1024)
        message = f'Upload is too large (limit {limit_mb} MB).'
        if wants_json():
            return api_error(message, 413)
        return render_template('error.html', code=413, title='File Too Large',
                               message=message), 413

    @app.errorhandler(422)
    def unprocessable(e):
        if wants_json():
            return api_error(getattr(e, 'description', None) or 'Validation failed', 422)
        return render_template('error.html', code=422, title='Validation Failed',
                               message='Some of the values sent were not valid.'), 422

    @app.errorhandler(429)
    def too_many_requests(e):
        if wants_json():
            return api_error('Too many requests. Please slow down.', 429)
        return render_template('error.html', code=429, title='Too Many Requests',
                               message='Please wait a moment and try again.'), 429

    @app.errorhandler(500)
    @app.errorhandler(Exception)
    def internal_error(e):
        # Let Werkzeug's own HTTP errors (404, 403, …) reach their handlers above;
        # only genuinely unexpected exceptions become a 500.
        if isinstance(e, HTTPException):
            return e

        # A failed write leaves the session dirty and poisons the next request.
        db.session.rollback()
        app.logger.exception('Unhandled exception on %s %s', request.method, request.path)

        if wants_json():
            payload = {}
            if app.config.get('DEBUG'):
                payload['detail'] = f'{type(e).__name__}: {e}'
            return api_error('Internal server error', 500, **payload)
        if app.config.get('DEBUG'):
            raise e  # keep the interactive debugger in development
        return render_template('error.html', code=500, title='Something Went Wrong',
                               message='We hit an unexpected error. Please try again.'), 500

    return app
