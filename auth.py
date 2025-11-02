from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash
from urllib.parse import urlparse, urljoin

import models

bp = Blueprint("auth", __name__)


def is_safe_url(request, target):
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('routes.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'

        user = models.users.get(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            next_page = request.args.get('next') or request.form.get('next')
            if next_page and is_safe_url(request, next_page):
                return redirect(next_page)
            return redirect(url_for('routes.dashboard'))
        else:
            return render_template('login.html', error='Invalid username or password')

    next_page = request.args.get('next', '')
    return render_template('login.html', next=next_page)


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

