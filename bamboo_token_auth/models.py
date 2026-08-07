# -*- coding: utf-8 -*-

from odoo import models, fields, api, http
from odoo.exceptions import AccessDenied
from odoo.http import request
from . import jwt_min as jwt


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
                return payload.get('uid')
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
