# -*- coding: utf-8 -*-
"""OCA's fastapi demo app must not be mounted.

It ships two endpoints, `/fastapi_demo` and `/fastapi/demo-multi` — the second one
inside the namespace this module owns. `hooks.drop_oca_demo_endpoints` removes the
records on every install/upgrade; this is the check that it still runs.
"""

from odoo.tests import tagged

from .common import BambooFastapiCase


@tagged("post_install", "-at_install")
class TestNoDemoEndpoint(BambooFastapiCase):

    def test_no_demo_records(self):
        self.assertFalse(
            self.env["fastapi.endpoint"].sudo().search_count([("app", "=", "demo")])
        )

    def test_demo_routes_are_gone(self):
        for path in ("/fastapi_demo/demo/", "/fastapi/demo-multi/demo/"):
            with self.subTest(path=path):
                self.assertEqual(self.url_open(path).status_code, 404)

    def test_our_endpoint_is_the_only_one(self):
        endpoint = self.env.ref(
            "bamboo_public_api_fastapi.fastapi_endpoint_bamboo_public"
        )
        self.assertEqual(endpoint.root_path, "/fastapi/v1")
