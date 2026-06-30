import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    # Convert asyncpg URL to psycopg2 for sync Flask
    _db_url = os.environ.get(
        'DATABASE_URL',
        'postgresql+asyncpg://myuser:MySecretPassword@localhost:5433/py_ecommerce'
    )
    SQLALCHEMY_DATABASE_URI = _db_url.replace('postgresql+asyncpg://', 'postgresql+pg8000://')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    WTF_CSRF_ENABLED = True
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'app', 'static', 'img', 'products')
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB
    BAKONG_TOKEN = os.environ.get('bakong_token')


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
