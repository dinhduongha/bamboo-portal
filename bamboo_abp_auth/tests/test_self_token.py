# -*- coding: utf-8 -*-
"""The tokens this module issues itself.

`/api/v1/auth/callback` (POST) mints these so a client stops presenting ABP's
token on every call. They are HS256 like bamboo_token_auth's, and the only thing
keeping the two apart is the `iss` claim — which is what most of this file is
about.
"""

import time

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import config


@tagged('post_install', '-at_install')
class TestSelfIssuedToken(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.bamboo_abp_auth.controllers.auth import AbpOidc

        cls.AbpOidc = AbpOidc
        cls.IrHttp = cls.env['ir.http']
        cls.user = cls.env.ref('base.user_admin')

    def _config(self, **values):
        for key, value in values.items():
            old = config.get(key)
            config[key] = value
            self.addCleanup(config.__setitem__, key, old)

    def _secret(self):
        return self.env['ir.config_parameter'].sudo().get_param('database.secret')

    def _encode(self, payload, secret=None):
        import jwt

        return jwt.encode(payload, secret or self._secret(), algorithm='HS256')

    def test_issue_then_validate(self):
        self._config(openid_jwt_secret='', openid_jwt_ttl='')
        token, expires_in = self.AbpOidc.issue_token(
            self.user, {'sub': 'abp-1', 'tenantid': 't-1'})
        self.assertEqual(expires_in, 86400)

        claims = self.AbpOidc.validate_self_token(token, self.env)
        self.assertEqual(claims['uid'], self.user.id)
        self.assertEqual(claims['iss'], self.AbpOidc.SELF_ISSUER)
        self.assertEqual(claims['abp_sub'], 'abp-1')
        self.assertEqual(claims['tenantid'], 't-1')

    def test_ttl_is_configurable(self):
        self._config(openid_jwt_ttl='60')
        _token, expires_in = self.AbpOidc.issue_token(self.user)
        self.assertEqual(expires_in, 60)

    def test_expired_is_rejected(self):
        now = int(time.time())
        token = self._encode({
            'iss': self.AbpOidc.SELF_ISSUER, 'uid': self.user.id,
            'iat': now - 100, 'exp': now - 10,
        })
        with self.assertRaises(UserError):
            self.AbpOidc.validate_self_token(token, self.env)

    def test_wrong_secret_is_rejected(self):
        now = int(time.time())
        token = self._encode({
            'iss': self.AbpOidc.SELF_ISSUER, 'uid': self.user.id,
            'iat': now, 'exp': now + 600,
        }, secret='not-the-database-secret')
        with self.assertRaises(UserError):
            self.AbpOidc.validate_self_token(token, self.env)

    def test_gate_claims_self_issued_but_not_bamboo_token_auth(self):
        """Both are HS256 signed with database.secret. `iss` is the whole line."""
        now = int(time.time())
        ours = self._encode({
            'iss': self.AbpOidc.SELF_ISSUER, 'uid': self.user.id,
            'iat': now, 'exp': now + 600,
        })
        self.assertTrue(self.IrHttp._token_is_ours(ours))

        # bamboo_token_auth's shape: same algorithm, same key, no issuer.
        theirs = self._encode({'uid': self.user.id, 'iat': now, 'exp': now + 600})
        self.assertFalse(self.IrHttp._token_is_ours(theirs))

    def test_archived_user_is_rejected(self):
        """Archiving is how access is revoked; a token minted before must die."""
        user = self.env['res.users'].create({
            'name': 'SSO Temp', 'login': 'sso.temp@example.test',
        })
        token, _ttl = self.AbpOidc.issue_token(user)
        self.assertEqual(
            self.IrHttp._user_from_self_token(self.env, token), user)

        user.active = False
        with self.assertRaises(Exception):
            self.IrHttp._user_from_self_token(self.env, token)
