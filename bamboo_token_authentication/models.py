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
        path). This is what makes "send both" robust: a stale/expired Bearer
        alongside a valid session must not hard-fail the request (which would
        bounce the user to /login in a loop).
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
