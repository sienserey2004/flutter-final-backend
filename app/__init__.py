from flask import Flask, render_template
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.pool import StaticPool
from config import config
from app.models import db, bcrypt, User

login_manager = LoginManager()
migrate = Migrate()


def _create_database_if_not_exists(database_url):
    """Create PostgreSQL database if it doesn't exist."""
    if 'postgresql' not in database_url:
        return
    
    try:
        from urllib.parse import urlparse
        parsed = urlparse(database_url)
        db_name = parsed.path.lstrip('/')
        
        # Try to use psycopg2 for admin operations (more reliable)
        admin_url = database_url.replace(f'/{db_name}', '/postgres')
        admin_url = admin_url.replace('+pg8000', '+psycopg2')
        admin_url = admin_url.replace('+asyncpg', '+psycopg2')
        if '+' not in admin_url:
            admin_url = admin_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
        
        try:
            # Use isolation_level=AUTOCOMMIT to execute DDL outside transaction
            engine = create_engine(
                admin_url,
                isolation_level='AUTOCOMMIT',
                echo=False,
                poolclass=StaticPool
            )
            with engine.connect() as conn:
                result = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
                if not result.fetchone():
                    conn.execute(text(f"CREATE DATABASE {db_name}"))
                    print(f"✓ Created database '{db_name}'")
                else:
                    print(f"✓ Database '{db_name}' already exists")
            engine.dispose()
        except ImportError:
            # Fallback: psycopg2 not available, try with pg8000
            print("⚠ psycopg2 not available, attempting with pg8000...")
            admin_url = database_url.replace(f'/{db_name}', '/postgres')
            engine = create_engine(
                admin_url,
                isolation_level='AUTOCOMMIT',
                echo=False,
                poolclass=StaticPool
            )
            with engine.connect() as conn:
                result = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
                if not result.fetchone():
                    conn.execute(text(f"CREATE DATABASE {db_name}"))
                    print(f"✓ Created database '{db_name}'")
                else:
                    print(f"✓ Database '{db_name}' already exists")
            engine.dispose()
    except Exception as e:
        print(f"⚠ Warning: Could not auto-create database: {type(e).__name__}: {e}")
        print("→ Please create the database manually or install psycopg2-binary")


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

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
            print("✓ Database tables created/verified")
        except ProgrammingError as e:
            if 'does not exist' in str(e):
                print(f"✗ Database still does not exist. Please ensure PostgreSQL is running and create the database manually:")
                print(f"   createdb py_ecommerce")
            else:
                print(f"Note: Database issue: {e}")
        except Exception as e:
            print(f"Note: Could not create tables: {type(e).__name__}: {e}")

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from app.routes.auth     import auth_bp
    from app.routes.products import products_bp
    from app.routes.cart     import cart_bp
    from app.routes.orders   import orders_bp
    from app.routes.admin    import admin_bp
    from app.routes.reviews  import reviews_bp
    from app.routes.main     import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp,     url_prefix='/auth')
    app.register_blueprint(products_bp, url_prefix='/products')
    app.register_blueprint(cart_bp,     url_prefix='/cart')
    app.register_blueprint(orders_bp,   url_prefix='/orders')
    app.register_blueprint(admin_bp,    url_prefix='/admin')
    app.register_blueprint(reviews_bp,  url_prefix='/reviews')

    # Jinja2 globals
    from datetime import datetime
    app.jinja_env.globals['now'] = datetime.utcnow

    # Error handlers
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('404.html'), 404

    return app
