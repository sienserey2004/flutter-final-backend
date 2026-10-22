import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
load_dotenv(os.path.join(BASE_DIR, '.env'))


def _normalize_db_url(url: str) -> str:
    """Normalize database URLs and make relative SQLite paths cwd-independent."""
    if url.startswith('sqlite:///'):
        sqlite_path = url[len('sqlite:///'):]
        if sqlite_path.startswith('/'):
            return url
        if sqlite_path.startswith('instance/'):
            sqlite_path = sqlite_path[len('instance/'):]
        absolute_path = os.path.abspath(os.path.join(INSTANCE_DIR, sqlite_path))
        return 'sqlite:///' + absolute_path
    if url.startswith('postgresql+psycopg2://'):
        return url
    if url.startswith('postgresql+asyncpg://'):
        return url.replace('postgresql+asyncpg://', 'postgresql+psycopg2://', 1)
    if url.startswith('postgresql+pg8000://'):
        return url.replace('postgresql+pg8000://', 'postgresql+psycopg2://', 1)
    if url.startswith('postgresql://') or url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql+psycopg2://', 1) \
                  .replace('postgresql://', 'postgresql+psycopg2://', 1)
    return url


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    os.makedirs(INSTANCE_DIR, exist_ok=True)
    _raw_db_url = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + os.path.join(INSTANCE_DIR, 'ecommerce.db')
    )
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(_raw_db_url)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    if SQLALCHEMY_DATABASE_URI.startswith('sqlite://'):
        SQLALCHEMY_ENGINE_OPTIONS = {
            'connect_args': {'check_same_thread': False},
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_pre_ping': True,
            'pool_recycle': 300,
            'connect_args': {
                'sslmode': 'require',
            },
        }

    WTF_CSRF_ENABLED = True
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'app', 'static', 'img', 'products')
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB
    BAKONG_TOKEN = os.environ.get('bakong_token')

    # Storefront
    STORE_NAME    = os.environ.get('STORE_NAME', 'NovaMart')
    STORE_TAGLINE = os.environ.get('STORE_TAGLINE', 'Everyday products, thoughtfully selected.')
    CONTACT_EMAIL = os.environ.get('CONTACT_EMAIL', 'support@example.com')
    CONTACT_PHONE = os.environ.get('CONTACT_PHONE', '+855 12 000 000')
    CONTACT_ADDRESS = os.environ.get('CONTACT_ADDRESS', 'Phnom Penh, Cambodia')
    # Applied to (subtotal − discount) at checkout. 0 = tax-inclusive pricing.
    TAX_RATE      = float(os.environ.get('TAX_RATE', '0') or 0)


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
