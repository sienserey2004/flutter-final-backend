from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.models import db, User, Role, Cart
from app.api import wants_json, api_ok, api_error, form_value
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

auth_bp = Blueprint('auth', __name__)


def _password_reset_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='password-reset')


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
            # Already signed in through the session cookie (e.g. Swagger UI or a
            # browser tab that logged in earlier). API clients re-posting their
            # credentials still expect a token, so mint a fresh one for this
            # account instead of returning a bare user object.
            return api_ok(current_user.to_dict(), token=current_user.generate_token())
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


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Start recovery without revealing whether an email exists."""
    email = (form_value('email', '') or '').strip().lower()
    user = User.query.filter_by(email=email, is_active=True).first()
    payload = {'message': 'If that email is registered, password reset instructions have been sent.'}
    if user:
        payload['reset_token'] = _password_reset_serializer().dumps({'user_id': user.user_id})
    if wants_json():
        if not current_app.config.get('DEBUG'):
            payload.pop('reset_token', None)
        return api_ok(payload)
    flash(payload['message'], 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    token = (form_value('token', '') or '').strip()
    password = form_value('password', '') or ''
    confirm = form_value('confirm', password) or ''
    if len(password) < 6:
        return api_error('Password must be at least 6 characters.', 422) if wants_json() else redirect(url_for('auth.login'))
    if password != confirm:
        return api_error('Passwords do not match.', 422) if wants_json() else redirect(url_for('auth.login'))
    try:
        data = _password_reset_serializer().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        return api_error('Reset token is invalid or expired.', 422) if wants_json() else redirect(url_for('auth.login'))
    user = User.query.get(data.get('user_id'))
    if not user or not user.is_active:
        return api_error('Reset token is invalid or expired.', 422) if wants_json() else redirect(url_for('auth.login'))
    user.set_password(password)
    db.session.commit()
    if wants_json():
        return api_ok(message='Password reset successfully.')
    flash('Password reset successfully. Please log in.', 'success')
    return redirect(url_for('auth.login'))


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


@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """API password change — unlike /profile, this requires the current password."""
    current_pass = form_value('current_password', '') or ''
    new_pass = form_value('new_password', '') or ''
    if not current_user.check_password(current_pass):
        return api_error('Current password is incorrect.', 422)
    if len(new_pass) < 6:
        return api_error('New password must be at least 6 characters.', 422)
    if new_pass == current_pass:
        return api_error('New password must be different from the current one.', 422)
    current_user.set_password(new_pass)
    db.session.commit()
    return api_ok(message='Password changed.')


@auth_bp.route('/delete-account', methods=['POST'])
@login_required
def delete_account():
    """Close the account. Orders reference the user, so the row is deactivated
    rather than removed — is_active=False blocks login and every bearer token."""
    if not current_user.check_password(form_value('password', '') or ''):
        return api_error('Password is incorrect.', 422)
    current_user.is_active = False
    db.session.commit()
    logout_user()
    return api_ok(message='Account deleted.')
