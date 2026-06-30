"""
manage.py — Flask CLI management commands.

Usage:
  flask db init        # initialise migrations folder (first time only)
  flask db migrate -m "initial"
  flask db upgrade

  flask create-admin   # create a quick admin user interactively
  flask seed-db        # seed sample data (dev only)
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
