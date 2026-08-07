# -*- coding: utf-8 -*-
"""The check that fails when OCA's fixed-user environment comes back.

`FastApiDispatcher` runs the app as `endpoint.user_id` (the public user). Without
the `odoo_env` override in ../dependencies.py, `/me` answers 401 for everybody,
including a caller holding a perfectly valid token — silently, because every
other route in this app reads the same either way.
"""

import json
import time

from odoo.tests import HttpCase, tagged

ROOT = '/bamboo/fastapi/v1'


@tagged('post_install', '-at_install')
class TestFastapiAuthEnv(HttpCase):

    def _bearer(self, user):
        """A bamboo_token_auth JWT for `user` — the HS256 flavour.

        The RS256/ABP flavour is not exercised here: it needs a live AuthServer
        to sign with. Both land in `request.env.uid` before the dispatcher runs,
        which is the only thing this module depends on, so one of them proves the
        seam. (A session cookie is the third source, covered below.)
        """
        from odoo.addons.bamboo_token_auth import jwt_min as jwt

        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret')
        now = int(time.time())
        return jwt.encode(
            {'uid': user.id, 'iat': now, 'exp': now + 3600},
            secret, algorithm='HS256',
        )

    def test_me_requires_authentication(self):
        res = self.url_open(ROOT + '/me')
        self.assertEqual(res.status_code, 401)
        self.assertFalse(res.json()['success'])

    def test_me_honours_bearer_token(self):
        user = self.env.ref('base.user_admin')
        res = self.url_open(
            ROOT + '/me',
            headers={'Authorization': 'Bearer %s' % self._bearer(user)},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()['data']
        # The point of the whole override: NOT the endpoint's public user.
        self.assertEqual(data['uid'], user.id)
        self.assertEqual(data['login'], user.login)
        # And the user's own default company, not whichever sorts first by name.
        self.assertEqual(data['company'], user.company_id.name)

    def test_me_honours_session_cookie(self):
        """Any auth source ir.http accepts, not just Bearer."""
        self.authenticate('admin', 'admin')
        res = self.url_open(ROOT + '/me')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['data']['login'], 'admin')

    def test_public_routes_still_anonymous(self):
        """The override must not turn a public read into an authenticated one."""
        res = self.url_open(ROOT + '/health')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['success'])
        res = self.url_open(ROOT + '/meta')
        self.assertEqual(res.status_code, 200)
        self.assertIn('apps', res.json()['data'])
        json.loads(res.content)  # valid JSON, not an Odoo HTML error page
