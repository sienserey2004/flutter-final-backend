from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.models import db, User, Role, Cart
from app.api import wants_json, api_ok, api_error, form_value

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        if wants_json():
            return api_ok(current_user.to_dict())
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        name     = (form_value('name', '') or '').strip()
        email    = (form_value('email', '') or '').strip().lower()
        password = form_value('password', '') or ''
        confirm  = form_value('confirm', '') or ''
        phone    = (form_value('phone', '') or '').strip()

        errors = []
        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')
        if password != confirm:
            errors.append('Passwords do not match.')
        if User.query.filter_by(email=email).first():
            errors.append('Email already registered.')

        if errors:
            if wants_json():
                return api_error('Validation failed', 422, errors=errors)
            for e in errors:
                flash(e, 'danger')
            return render_template('auth/register.html',
                                   name=name, email=email, phone=phone)

        user = User(name=name, email=email, phone=phone)
        user.set_password(password)

        # Assign Customer role by default
        customer_role = Role.query.filter_by(role_name='Customer').first()
        if not customer_role:
            customer_role = Role(role_name='Customer')
            db.session.add(customer_role)
            db.session.flush()
        user.roles.append(customer_role)

        # Create empty cart
        db.session.add(user)
        db.session.flush()
        cart = Cart(user_id=user.user_id)
        db.session.add(cart)
        db.session.commit()

        flash('Account created! Please log in.', 'success')
        if wants_json():
            return api_ok(user.to_dict(), status=201)
        return redirect(url_for('auth.login'))

    if wants_json():
        return api_error('GET not supported for registration; POST name/email/password/confirm.', 405)
    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if wants_json():
            return api_ok(current_user.to_dict())
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email    = (form_value('email', '') or '').strip().lower()
        password = form_value('password', '') or ''
        remember = form_value('remember') in ('on', True, 'true', '1')

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and not user.is_active:
            # Correct credentials, suspended account — say so plainly rather
            # than letting login_user() fail with a misleading "wrong password".
            msg = 'This account has been deactivated. Please contact support.'
            if wants_json():
                return api_error(msg, 403)
            flash(msg, 'warning')
            return render_template('auth/login.html')

        if user and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.name}!', 'success')
            if wants_json():
                return api_ok(user.to_dict(), token=user.generate_token())
            return redirect(next_page or url_for('main.index'))

        if wants_json():
            return api_error('Invalid email or password.', 401)
        flash('Invalid email or password.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    if wants_json():
        return api_ok(message='Logged out.')
    return redirect(url_for('main.index'))


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.name  = (form_value('name', current_user.name) or '').strip()
        current_user.phone = (form_value('phone', current_user.phone) or '').strip()
        new_pass = form_value('new_password', '') or ''
        if new_pass:
            if len(new_pass) < 6:
                if wants_json():
                    return api_error('New password must be at least 6 characters.', 422)
                flash('New password must be at least 6 characters.', 'danger')
                return redirect(url_for('auth.profile'))
            current_user.set_password(new_pass)
        db.session.commit()
        flash('Profile updated.', 'success')
        if wants_json():
            return api_ok(current_user.to_dict())
    if wants_json():
        return api_ok(current_user.to_dict())
    return render_template('auth/profile.html')
