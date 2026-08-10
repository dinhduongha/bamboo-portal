# -*- coding: utf-8 -*-
"""Generic ORM RPC: identity, wire format, and the guards that keep it safe.

The two routes deliberately do NOT return the public API's envelope, so the
assertions here are about the JSON-RPC / raw shapes. If someone widens the
envelope monkeypatch in models/fastapi_endpoint.py past `/public`, these fail.
"""

from odoo import release
from odoo.tests import tagged

from .common import RPC_ROOT, BambooFastapiCase

CALL_KW = RPC_ROOT + "/dataset/call_kw"
JSON2 = RPC_ROOT + "/json2"


@tagged("post_install", "-at_install")
class TestRpcCallKw(BambooFastapiCase):

    def _post(self, path, payload, headers=None):
        return self.opener.post(
            self.base_url() + path, json=payload, headers=headers or {}
        )

    def test_anonymous_is_refused(self):
        res = self._post(
            CALL_KW + "/res.partner/search_read",
            {"params": {"args": [[], ["name"]], "kwargs": {"limit": 1}}},
        )
        self.assertEqual(res.status_code, 401)

    def test_bearer_token_can_call(self):
        res = self._post(
            CALL_KW + "/res.partner/search_read",
            {"jsonrpc": "2.0", "id": 7, "params": {"args": [[], ["name"]], "kwargs": {"limit": 1}}},
            self._auth_headers(),
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["id"], 7)
        self.assertNotIn("error", body)
        self.assertEqual(len(body["result"]), 1)
        # NOT the public API envelope — a client unwrapping `result` must find it.
        self.assertNotIn("success", body)

    def test_path_and_body_must_agree(self):
        res = self._post(
            CALL_KW + "/res.partner/search_read",
            {"params": {"model": "res.users", "args": [[]], "kwargs": {}}},
            self._auth_headers(),
        )
        self.assertEqual(res.status_code, 422)

    def test_private_method_is_refused(self):
        """`_read_format` is the probe because it is private on both 18 and 19 —
        `_read` does not exist on 18, so it would test AttributeError instead."""
        res = self._post(
            CALL_KW + "/res.partner/_read_format",
            {"jsonrpc": "2.0", "id": 1, "params": {"args": [[1]], "kwargs": {}}},
            self._auth_headers(),
        )
        # JSON-RPC keeps a 200 and puts the failure in the body, like core.
        self.assertEqual(res.status_code, 200)
        self.assertIn("AccessError", res.json()["error"]["data"]["name"])

    def test_unknown_model_is_404_in_the_body(self):
        res = self._post(
            CALL_KW + "/no.such.model/search_read",
            {"jsonrpc": "2.0", "id": 1, "params": {"args": [[]], "kwargs": {}}},
            self._auth_headers(),
        )
        self.assertEqual(res.json()["error"]["code"], 404)

    def test_a_failed_call_does_not_poison_the_transaction(self):
        """The savepoint: without it the cursor stays aborted after a failure and
        every later call in the same request cycle dies with InternalError."""
        headers = self._auth_headers()
        self._post(
            CALL_KW + "/res.partner/_read_format",
            {"params": {"args": [[1]], "kwargs": {}}},
            headers,
        )
        res = self._post(
            CALL_KW + "/res.partner/search_count",
            {"jsonrpc": "2.0", "id": 2, "params": {"args": [[]], "kwargs": {}}},
            headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json()["result"], int)


@tagged("post_install", "-at_install")
class TestRpcJson2(BambooFastapiCase):
    """`/json2` is the FastAPI equivalent of core's `/json/2` (Odoo 19+)."""

    def setUp(self):
        super().setUp()
        if release.version_info[0] < 19:
            self.skipTest("json2 is only served on Odoo 19+")

    def _post(self, path, payload, headers=None):
        return self.opener.post(
            self.base_url() + path, json=payload, headers=headers or {}
        )

    def test_returns_the_raw_value(self):
        res = self._post(
            JSON2 + "/res.partner/search_read",
            {"domain": [], "fields": ["name"], "limit": 1},
            self._auth_headers(),
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        # No envelope, no JSON-RPC wrapper: the value itself.
        self.assertIsInstance(body, list)
        self.assertIn("name", body[0])

    def test_matches_core_json_2(self):
        """Same call, same body — the whole point of mirroring the core route."""
        headers = self._auth_headers()
        payload = {"domain": [], "fields": ["name"], "limit": 2}
        ours = self._post(JSON2 + "/res.partner/search_read", payload, headers)
        # Core's /json/2 needs an API key. Mint it AS admin, not sudo: `_generate`
        # keys the record to `env.user`, and the test env's superuser is OdooBot,
        # who is archived — `_check_credentials` filters on `u.active`, so such a
        # key silently never authenticates.
        key = (
            self.env["res.users.apikeys"]
            .with_user(self.env.ref("base.user_admin"))
            ._generate("rpc", "bamboo-parity-test", None)
        )
        self.env.flush_all()
        core = self._post(
            "/json/2/res.partner/search_read",
            payload,
            {"Authorization": "Bearer %s" % key},
        )
        self.assertEqual(core.status_code, 200)
        self.assertEqual(ours.json(), core.json())

    def test_anonymous_is_refused(self):
        res = self._post(JSON2 + "/res.partner/search_read", {"domain": []})
        self.assertEqual(res.status_code, 401)

    def test_unknown_model_is_404(self):
        res = self._post(
            JSON2 + "/no.such.model/search_read", {}, self._auth_headers()
        )
        self.assertEqual(res.status_code, 404)

    def test_private_method_is_403(self):
        res = self._post(JSON2 + "/res.partner/_read_format", {}, self._auth_headers())
        self.assertEqual(res.status_code, 403)

    def test_ids_on_an_api_model_method_is_422(self):
        res = self._post(
            JSON2 + "/res.partner/search_read",
            {"ids": [1], "domain": []},
            self._auth_headers(),
        )
        self.assertEqual(res.status_code, 422)

    def test_wrong_content_type_is_415(self):
        res = self.opener.post(
            self.base_url() + JSON2 + "/res.partner/search_read",
            data="domain=[]",
            headers=self._auth_headers(),
        )
        self.assertEqual(res.status_code, 415)

    def test_catch_all_explains_the_route(self):
        res = self.url_open(JSON2, headers=self._auth_headers())
        self.assertEqual(res.status_code, 404)
        self.assertIn("json2/<model>/<method>", res.json()["message"])
