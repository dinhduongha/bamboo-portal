# -*- coding: utf-8 -*-
"""The check that fails when OCA's fixed-user environment comes back.

`FastApiDispatcher` runs the app as `endpoint.user_id` (the public user). Without
the `odoo_env` override in ../dependencies.py, `/me` answers "nobody" for
everybody, including a caller holding a perfectly valid token — silently, because
every other public route in this app reads the same either way.
"""

import json

from odoo import release
from odoo.tests import tagged

from .common import PUBLIC_ROOT, BambooFastapiCase


@tagged("post_install", "-at_install")
class TestFastapiAuthEnv(BambooFastapiCase):

    def test_me_anonymous_is_null(self):
        """Same answer as the controller: 200 with `data: null`, not a 401."""
        res = self.url_open(PUBLIC_ROOT + "/me")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        self.assertIsNone(body["data"])

    def test_me_honours_bearer_token(self):
        user = self.env.ref("base.user_admin")
        res = self.url_open(PUBLIC_ROOT + "/me", headers=self._auth_headers(user))
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        # The point of the whole override: NOT the endpoint's public user.
        self.assertEqual(data["uid"], user.id)
        self.assertEqual(data["login"], user.login)

    def test_me_honours_session_cookie(self):
        """Any auth source ir.http accepts, not just Bearer."""
        self.authenticate("admin", "admin")
        res = self.url_open(PUBLIC_ROOT + "/me")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["login"], "admin")

    def test_public_routes_still_anonymous(self):
        """The override must not turn a public read into an authenticated one."""
        res = self.url_open(PUBLIC_ROOT + "/health")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])
        res = self.url_open(PUBLIC_ROOT + "/meta")
        self.assertEqual(res.status_code, 200)
        self.assertIn("apps", res.json()["data"])
        json.loads(res.content)  # valid JSON, not an Odoo HTML error page

    def test_meta_advertises_the_public_root(self):
        """`api_root` is what a client sets as its base URL — the /public subtree,
        not the app root (which also carries the un-enveloped RPC routes)."""
        res = self.url_open(PUBLIC_ROOT + "/meta")
        self.assertEqual(res.json()["data"]["api_root"], PUBLIC_ROOT)

    def _skip_login_on_18(self):
        """`/auth/login` cannot be exercised by HttpCase on Odoo 18.

        18's `res.users._login` is a classmethod that opens its own
        `cls.pool.cursor()`. Under a test that is a `TestCursor`, whose
        `__init__` acquires a lock the running request already holds — the
        worker thread blocks forever and the suite hangs. Odoo 19 dropped the
        nested cursor (`_login` runs on `self`), so the check runs there.

        The route itself works on 18 — only this harness cannot drive it.
        """
        if release.version_info[0] < 19:
            self.skipTest("res.users._login opens a nested cursor on 18 (deadlocks HttpCase)")

    def test_login_returns_a_usable_token(self):
        self._skip_login_on_18()
        res = self.opener.post(
            self.base_url() + PUBLIC_ROOT + "/auth/login",
            json={"login": "admin", "password": "admin"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertTrue(data["access_token"])
        me = self.url_open(
            PUBLIC_ROOT + "/me",
            headers={"Authorization": "Bearer %s" % data["access_token"]},
        )
        self.assertEqual(me.json()["data"]["login"], "admin")

    def test_login_rejects_bad_credentials(self):
        self._skip_login_on_18()
        res = self.opener.post(
            self.base_url() + PUBLIC_ROOT + "/auth/login",
            json={"login": "admin", "password": "nope"},
        )
        self.assertEqual(res.status_code, 401)
        self.assertFalse(res.json()["success"])
