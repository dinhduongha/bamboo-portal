# -*- coding: utf-8 -*-

import hmac
import secrets
import time

from odoo import models, fields, api, http
from odoo.exceptions import AccessDenied
from odoo.http import request
from . import jwt_min as jwt


def issue_token(env, uid, ttl=90 * 24 * 3600):
    """Mint the HS256 bearer every Bamboo login hands out.

    `stk` is Odoo's own session token for a random `jti`: an HMAC over the
    user's id, login, password hash, active flag and database.secret. Change
    any of them (password reset, "log out all devices", archive) and every
    token minted before stops matching -- the same rule Odoo applies to its
    session cookies, with no token table to keep.
    """
    jti = secrets.token_urlsafe(16)
    now = int(time.time())
    return jwt.encode({
        'uid': uid, 'iat': now, 'exp': now + ttl, 'jti': jti,
        'stk': env['res.users'].sudo().browse(uid)._compute_session_token(jti),
    }, env['ir.config_parameter'].sudo().get_param('database.secret'),
        algorithm='HS256')


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _bearer_uid(cls):
        """Decode the `Authorization: Bearer <jwt>` header to a uid, or None.

        Returns None on a missing/expired/invalid token instead of raising, so
        the auth methods fall back to `super()` (the standard session-cookie
        path). This is what makes "send both" robust: a stale Bearer alongside a
        valid session cookie must not break the request.
        """
        token = request.httprequest.headers.get('Authorization')
        if token and token.startswith('Bearer '):
            try:
                secret = request.env['ir.config_parameter'].sudo().get_param('database.secret')
                payload = jwt.decode(token[7:], secret, algorithms=["HS256"])
                uid, jti = payload.get('uid'), payload.get('jti')
                if not (uid and jti):
                    return None
                # Revoked when the user's password/login/active changed since
                # the token was minted (see `issue_token`).
                stk = request.env['res.users'].sudo().browse(
                    uid)._compute_session_token(jti)
                if not stk or not hmac.compare_digest(
                        stk, payload.get('stk') or ''):
                    return None
                return uid
            except Exception:
                return None
        return None

    @classmethod
    def _auth_method_user(cls):
        uid = cls._bearer_uid()
        if uid:
            # Use update_env instead of direct uid assignment (Odoo 18 compatibility)
            request.update_env(user=uid)
        else:
            super(IrHttp, cls)._auth_method_user()

    @classmethod
    def _auth_method_public(cls):
        # Honour the bearer on public routes too (e.g. the mail edit/reaction
        # controllers are auth="public" but need request.env.user to attribute
        # the action to the current user).
        uid = cls._bearer_uid()
        if uid:
            request.update_env(user=uid)
        else:
            super(IrHttp, cls)._auth_method_public()

    @classmethod
    def _auth_method_bearer(cls):
        """Accept our JWT on `auth='bearer'` routes — notably /json/2.

        Odoo's own bearer method treats the token as an `res.users.apikeys`
        key and 401s ("Invalid apikey") on anything else, and it only falls
        back to the session cookie for top-level browser navigations
        (Sec-Fetch-Dest: document …), which a fetch/XHR client can never send.
        So without this, /json/2/<model>/<method> is unreachable for the app
        even with a perfectly valid token.

        Same fail-open contract as the two methods above: an absent, expired or
        malformed token returns None from `_bearer_uid` and we defer to
        `super()`, so real API keys and the session path keep working.
        """
        uid = cls._bearer_uid()
        if uid:
            request.update_env(user=uid)
            # Stateless, matching Odoo's own bearer branch: a token-authenticated
            # request must not rewrite the session on disk.
            request.session.can_save = False
        else:
            super(IrHttp, cls)._auth_method_bearer()
