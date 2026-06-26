# -*- coding: utf-8 -*-
"""Public-site authentication: signup / login / logout / me.

Classic email+password for the public/portal site (separate from the internal
Bamboo client's per-account auth). Login uses Odoo's session (cookie) so the
`withCredentials` public client + the auth='user' /portal endpoints just work.
Signup creates a `portal` (share=True) user.
"""
import time

from odoo import http
from odoo.http import request

from .common import API_ROOT, err, ok


def _issue_token(uid):
    """Mint a JWT compatible with bamboo_token_authentication's Bearer auth
    (its ir.http override decodes `database.secret`/HS256 on public+user routes).
    Returns '' when that module isn't installed (caller falls back to session)."""
    try:
        from odoo.addons.bamboo_token_authentication import jwt_min as jwt
    except ImportError:
        return ''
    secret = request.env['ir.config_parameter'].sudo().get_param('database.secret')
    now = int(time.time())
    return jwt.encode(
        {'uid': uid, 'iat': now, 'exp': now + 90 * 24 * 3600},
        secret, algorithm='HS256',
    )


def _user_dict(user, token=None):
    data = {
        'uid': user.id,
        'name': user.name,
        'login': user.login,
        'email': user.email or '',
        'partner_id': user.partner_id.id,
        'share': user.share,
    }
    if token:
        data['access_token'] = token
    return data


def _current_user():
    """The logged-in user, or None when the request is the public/anonymous user."""
    user = request.env.user
    if not user or user.id == request.env.ref('base.public_user').id:
        return None
    return user


class BambooPublicAuth(http.Controller):

    @http.route(API_ROOT + '/me', type='http', auth='public', methods=['GET'], csrf=False)
    def me(self, **kw):
        user = _current_user()
        return ok(data=_user_dict(user) if user else None)

    @http.route(API_ROOT + '/auth/login', type='http', auth='public', methods=['POST'], csrf=False)
    def login(self, **kw):
        from .common import read_body
        body = read_body()
        login = (body.get('login') or body.get('email') or '').strip()
        password = body.get('password') or ''
        if not login or not password:
            return err('Login and password are required', 422)
        try:
            request.session.authenticate(
                request.env, {'login': login, 'password': password, 'type': 'password'},
            )
        except Exception as exc:
            return err('Invalid credentials: %s' % exc, 401)
        user = _current_user()
        if not user:
            return err('Invalid credentials', 401)
        return ok(data=_user_dict(user, _issue_token(user.id)))

    @http.route(API_ROOT + '/auth/signup', type='http', auth='public', methods=['POST'], csrf=False)
    def signup(self, **kw):
        from .common import read_body
        body = read_body()
        name = (body.get('name') or '').strip()
        email = (body.get('email') or '').strip()
        password = body.get('password') or ''
        if not name or not email or not password:
            return err('Name, email and password are required', 422)

        Users = request.env['res.users'].sudo()
        if Users.search_count([('login', '=', email)]):
            return err('An account with this email already exists', 409)

        portal_group = request.env.ref('base.group_portal')
        # Odoo 19 renamed res.users.groups_id → group_ids.
        group_field = 'group_ids' if 'group_ids' in Users._fields else 'groups_id'
        try:
            Users.create({
                'name': name,
                'login': email,
                'email': email,
                'password': password,
                group_field: [(6, 0, [portal_group.id])],
            })
        except Exception as exc:
            return err('Could not create account: %s' % exc, 400)

        # Log the new user in immediately (session cookie).
        try:
            request.session.authenticate(
                request.env, {'login': email, 'password': password, 'type': 'password'},
            )
        except Exception:
            return err('Account created but auto-login failed; please log in', 200)
        user = _current_user()
        return ok(data=_user_dict(user, _issue_token(user.id)) if user else None, status=201)

    @http.route(API_ROOT + '/auth/logout', type='http', auth='public', methods=['POST'], csrf=False)
    def logout(self, **kw):
        request.session.logout(keep_db=True)
        return ok(data={'logged_out': True})
