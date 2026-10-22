"""
manage.py — Flask CLI management commands.

Usage:
  flask db init        # initialise migrations folder (first time only)
  flask db migrate -m "initial"
  flask db upgrade

  flask create-admin   # create a quick admin user interactively
  flask create-superadmin            # create a Super Admin interactively
  flask promote-superadmin --email X # make an existing user a Super Admin
  flask seed-db        # seed sample data (dev only)
  flask localize-images [--dry-run] [--copy-static]  # store all images under static/images/uploads
  flask fetch-stock-photos           # replace product photos with free Pexels photos (PEXELS_API_KEY)
"""
import os
import click
from flask.cli import with_appcontext
from run import app
from app.models import db, User, Role, Cart, BakongMerchant


@app.cli.command('create-admin')
@click.option('--name',     prompt='Admin name',     default='Admin')
@click.option('--email',    prompt='Admin email',    default='admin@shop.com')
@click.option('--password', prompt='Admin password', hide_input=True, confirmation_prompt=True)
@with_appcontext
def create_admin(name, email, password):
    """Create an admin user."""
    existing = User.query.filter_by(email=email).first()
    if existing:
        click.echo(f'User {email} already exists.')
        return

    admin_role = Role.query.filter_by(role_name='Admin').first()
    if not admin_role:
        admin_role = Role(role_name='Admin')
        db.session.add(admin_role)

    customer_role = Role.query.filter_by(role_name='Customer').first()
    if not customer_role:
        customer_role = Role(role_name='Customer')
        db.session.add(customer_role)

    user = User(name=name, email=email)
    user.set_password(password)
    user.roles.append(admin_role)
    user.roles.append(customer_role)
    db.session.add(user)
    db.session.flush()
    db.session.add(Cart(user_id=user.user_id))
    db.session.commit()
    click.echo(f'✓ Admin user {email} created.')


def _get_role(role_name):
    role = Role.query.filter_by(role_name=role_name).first()
    if not role:
        role = Role(role_name=role_name)
        db.session.add(role)
        db.session.flush()
    return role


@app.cli.command('create-superadmin')
@click.option('--name',     prompt='Super Admin name',     default='Super Admin')
@click.option('--email',    prompt='Super Admin email',    default='superadmin@shop.com')
@click.option('--password', prompt='Super Admin password', hide_input=True, confirmation_prompt=True)
@with_appcontext
def create_superadmin(name, email, password):
    """Create a Super Admin, who can switch admin modules on and off."""
    if User.query.filter_by(email=email).first():
        click.echo(f'User {email} already exists — use promote-superadmin.')
        return

    roles = [_get_role('SuperAdmin'), _get_role('Customer')]
    user = User(name=name, email=email)
    user.set_password(password)
    db.session.add(user)
    for r in roles:
        user.roles.append(r)
    db.session.flush()
    db.session.add(Cart(user_id=user.user_id))
    db.session.commit()
    click.echo(f'✓ Super Admin {email} created.')


@app.cli.command('promote-superadmin')
@click.option('--email', prompt='User email')
@with_appcontext
def promote_superadmin(email):
    """Give an existing user the Super Admin role."""
    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user:
        click.echo(f'No user with email {email}.')
        return
    if user.is_super_admin():
        click.echo(f'{email} is already a Super Admin.')
        return
    user.roles.append(_get_role('SuperAdmin'))
    db.session.commit()
    click.echo(f'✓ {email} is now a Super Admin.')


@app.cli.command('create-sample-merchant')
@with_appcontext
def create_sample_merchant():
    """Create a sample Bakong merchant for testing."""
    from app.models import BakongMerchant
    merchant = BakongMerchant(
        merchant_name='Sample Ecommerce',
        bank_account='sien_serey@bkrt',
        merchant_city='Phnom Penh',
        terminal_label='ECOM001'
    )
    db.session.add(merchant)
    db.session.commit()
    click.echo('✓ Sample Bakong merchant created.')


@app.cli.command('create-sample-merchant')
@with_appcontext
def create_sample_merchant():
    """Create a sample Bakong merchant for testing."""
    merchant = BakongMerchant(
        merchant_name='Sample Ecommerce',
        bank_account='sien_serey@bkrt',
        merchant_city='Phnom Penh',
        terminal_label='ECOM001'
    )
    db.session.add(merchant)
    db.session.commit()
    click.echo('✓ Sample Bakong merchant created.')


@app.cli.command('seed-db')
@with_appcontext
def seed_db():
    """Seed the database with sample data."""
    import subprocess, sys
    subprocess.run([sys.executable, 'seed.py'], check=True)


@app.cli.command('localize-images')
@click.option('--dry-run', is_flag=True, help='Only list what would change.')
@click.option('--copy-static', is_flag=True,
              help='Also copy images already under static/ (e.g. seed images) into uploads/.')
@with_appcontext
def localize_images(dry_run, copy_static):
    """Download every external image URL into app/static/images/uploads and
    point the database at the local copy."""
    import os
    import shutil
    from urllib.parse import urlparse
    from app.models import Brand, Category, ProductImage, ProductVariant, Bundle
    from app.utils import download_image_to_static, is_external_url, UPLOAD_SUBDIR

    static_root = app.static_folder
    copied = {}  # (source path, folder) -> new relative path, so shared files are copied once

    def copy_into_uploads(rel_path, folder):
        key = (rel_path, folder)
        if key in copied:
            return copied[key]
        src = os.path.join(static_root, rel_path)
        if not os.path.isfile(src):
            raise FileNotFoundError(f'{rel_path} does not exist')
        rel_dir = f'{UPLOAD_SUBDIR}/{folder}'
        name, ext = os.path.splitext(os.path.basename(rel_path))
        candidate, n = f'{name}{ext}', 2
        while os.path.exists(os.path.join(static_root, rel_dir, candidate)):
            candidate, n = f'{name}-{n}{ext}', n + 1
        if not dry_run:
            os.makedirs(os.path.join(static_root, rel_dir), exist_ok=True)
            shutil.copy2(src, os.path.join(static_root, rel_dir, candidate))
        copied[key] = f'{rel_dir}/{candidate}'
        return copied[key]

    targets = [
        (Brand, 'logo', 'brands'),
        (Category, 'image', 'categories'),
        (ProductImage, 'url', 'products'),
        (ProductVariant, 'image', 'variants'),
        (Bundle, 'image', 'bundles'),
    ]
    moved = failed = 0
    for model, field, folder in targets:
        for row in model.query.all():
            value = getattr(row, field)
            label = f'{model.__tablename__}.{field} #{row.__mapper__.primary_key_from_instance(row)[0]}'
            if not is_external_url(value):
                if not (copy_static and value) or value.startswith(UPLOAD_SUBDIR + '/'):
                    continue
                try:
                    new_value = copy_into_uploads(value, folder)
                except OSError as exc:
                    failed += 1
                    click.echo(f'✗ {label}: {exc}')
                    continue
                if not dry_run:
                    setattr(row, field, new_value)
                    moved += 1
                click.echo(f'{"  " if dry_run else "✓ "}{label}: {value} -> {new_value}')
                continue
            parsed = urlparse(value)
            # Our own server's /static/ URLs: keep the file, just store the relative path.
            if parsed.hostname in ('127.0.0.1', 'localhost', '0.0.0.0') and parsed.path.startswith('/static/'):
                new_value = parsed.path[len('/static/'):]
            elif dry_run:
                click.echo(f'  {label}: {value}')
                continue
            else:
                try:
                    new_value = download_image_to_static(value, folder)
                except Exception as exc:  # network error, 404, not an image …
                    failed += 1
                    click.echo(f'✗ {label}: {exc}')
                    continue
            if dry_run:
                click.echo(f'  {label}: {value} -> {new_value}')
                continue
            setattr(row, field, new_value)
            moved += 1
            click.echo(f'✓ {label} -> {new_value}')
    if not dry_run:
        db.session.commit()
        click.echo(f'Done: {moved} image(s) stored locally, {failed} failed.')


# Pexels search phrase per product type; a keyword in the product name wins.
STOCK_PHOTO_QUERIES = {
    'Cleanser': 'facial cleanser bottle',
    'Toner': 'toner bottle skincare',
    'Serum': 'serum dropper bottle',
    'Ampoule': 'serum dropper bottle',
    'Spot Treatment': 'skincare cream tube',
    'Moisturizer': 'face cream jar',
    'Mask': 'face mask cream jar',
    'Eye Cream': 'eye cream jar',
    'Exfoliant': 'skincare bottle',
    'Sunscreen': 'sunscreen bottle',
    'Lip Care': 'lip balm',
}
STOCK_PHOTO_NAME_QUERIES = {
    'sheet mask': 'sheet mask face',
    'clay': 'clay mask skincare',
    'body lotion': 'body lotion bottle',
    'balm': 'skincare balm jar',
}


@app.cli.command('fetch-stock-photos')
@click.option('--per-product', default=3, show_default=True, help='Gallery photos per product.')
@click.option('--product-id', type=int, multiple=True, help='Only these products (repeatable).')
@click.option('--skip-photo', type=int, multiple=True, help='Pexels photo id to never use (repeatable).')
@with_appcontext
def fetch_stock_photos(per_product, product_id, skip_photo):
    """Replace product gallery images with free Pexels stock photos stored in
    app/static/images/uploads/products (needs PEXELS_API_KEY in .env)."""
    import json
    import requests
    from app.models import Product, ProductImage
    from app.utils import download_image_to_static, delete_uploaded_image, slugify

    key = os.environ.get('PEXELS_API_KEY')
    if not key:
        raise click.ClickException('Set PEXELS_API_KEY in backend/.env (free key: https://www.pexels.com/api/).')

    results, used = {}, set(skip_photo)

    def next_photo(query):
        if query not in results:
            resp = requests.get('https://api.pexels.com/v1/search', timeout=30,
                                headers={'Authorization': key},
                                params={'query': query, 'per_page': 80, 'orientation': 'square'})
            resp.raise_for_status()
            results[query] = resp.json().get('photos', [])
        for photo in results[query]:
            if photo['id'] not in used:
                used.add(photo['id'])
                return photo
        return None

    credits_path = os.path.join(app.static_folder, 'images', 'uploads', 'products', 'CREDITS.json')
    credits = json.load(open(credits_path)) if os.path.exists(credits_path) else {}

    query = Product.query.order_by(Product.product_id)
    if product_id:
        query = query.filter(Product.product_id.in_(product_id))
    for product in query:
        lowered = product.name.lower()
        search = next((q for word, q in STOCK_PHOTO_NAME_QUERIES.items() if word in lowered),
                      STOCK_PHOTO_QUERIES.get(product.product_type or '', 'skincare product'))
        new_paths = []
        for _ in range(per_product):
            photo = next_photo(search)
            if not photo:
                break
            path = download_image_to_static(photo['src']['large'], 'products')
            new_paths.append(path)
            credits[path] = {'photographer': photo['photographer'], 'pexels_url': photo['url'],
                             'pexels_id': photo['id'], 'product': product.name}
        if not new_paths:
            click.echo(f'✗ {product.name}: no photos for "{search}"')
            continue

        old = list(product.images)
        for img in old:
            path = img.url
            db.session.delete(img)
            delete_uploaded_image(path)
            credits.pop(path, None)
        for i, path in enumerate(new_paths):
            db.session.add(ProductImage(product_id=product.product_id, url=path, sort_order=i,
                                        is_primary=(i == 0),
                                        alt_text=f'{product.name} — photo {i + 1}'))
        for variant in product.variants:
            if variant.image and variant.image.startswith('images/uploads/'):
                if not any(v.image == variant.image for v in product.variants if v is not variant):
                    delete_uploaded_image(variant.image)
            variant.image = None  # falls back to the product's primary photo
        db.session.commit()
        click.echo(f'✓ {product.name}: {len(new_paths)} photo(s) for "{search}"')

    with open(credits_path, 'w') as fh:
        json.dump(credits, fh, indent=2)
    click.echo(f'Credits written to {os.path.relpath(credits_path)}')
