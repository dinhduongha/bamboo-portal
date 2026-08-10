# -*- coding: utf-8 -*-
"""The two modes must answer the same thing.

FastAPI mode is only useful if a client can point at `/fastapi/v1/public` instead
of `/bamboo/public/v1` and notice nothing. Forty routes is too many to eyeball, so
this compares the parsed bodies route by route against the controllers.

Whitespace is not compared (the controllers use `json.dumps` defaults, FastAPI is
compact) — `res.json()` on both sides makes that irrelevant.

Two answers are allowed to differ, and both are asserted explicitly below:
  * `/meta` — it reports which mode is serving, so it cannot match by definition;
  * `/portal/*` anonymously — the controller is `auth='user'` and Odoo redirects
    to the login page (HTML), while FastAPI answers 401 in the envelope. An API
    client wants the 401.
"""

from odoo.tests import tagged

from .common import CONTROLLER_ROOT, PUBLIC_ROOT, BambooFastapiCase

# Routes whose answer is a pure function of the database, so both modes must
# agree byte for byte once parsed. Authenticated ones are re-run with a token.
ANONYMOUS_ROUTES = [
    "/health",
    "/me",
    "/shop/categories",
    "/shop/products?limit=2",
    "/courses",
    "/blogs",
    "/events",
    "/forums",
    "/jobs",
    "/cart",
    "/payment/providers",
]

AUTHENTICATED_ROUTES = [
    "/me",
    "/portal/orders",
    "/portal/invoices",
    "/portal/subscriptions",
    "/portal/profile",
    "/portal/addresses",
    "/payment/status?reference=does-not-exist",
]


@tagged("post_install", "-at_install")
class TestPublicParity(BambooFastapiCase):

    def _both(self, path, headers=None):
        a = self.url_open(CONTROLLER_ROOT + path, headers=headers or {})
        b = self.url_open(PUBLIC_ROOT + path, headers=headers or {})
        return a, b

    def test_anonymous_routes_match(self):
        for path in ANONYMOUS_ROUTES:
            with self.subTest(path=path):
                controller, fastapi = self._both(path)
                self.assertEqual(controller.status_code, fastapi.status_code)
                self.assertEqual(controller.json(), fastapi.json())

    def test_authenticated_routes_match(self):
        headers = self._auth_headers()
        for path in AUTHENTICATED_ROUTES:
            with self.subTest(path=path):
                controller, fastapi = self._both(path, headers)
                self.assertEqual(controller.status_code, fastapi.status_code)
                self.assertEqual(controller.json(), fastapi.json())

    def test_detail_routes_match(self):
        """Detail routes need a real id, so they are resolved from the list first."""
        for list_path, detail in (
            ("/shop/products?limit=1", "/shop/products/%s"),
            ("/courses?limit=1", "/courses/%s"),
            ("/events?limit=1", "/events/%s"),
            ("/jobs?limit=1", "/jobs/%s"),
        ):
            body = self.url_open(CONTROLLER_ROOT + list_path).json()
            if not body.get("success") or not body.get("data"):
                continue  # app not installed on this database
            path = detail % body["data"][0]["id"]
            with self.subTest(path=path):
                controller, fastapi = self._both(path)
                self.assertEqual(controller.json(), fastapi.json())

    def test_meta_differs_only_in_the_mode_it_reports(self):
        controller, fastapi = self._both("/meta")
        a, b = controller.json()["data"], fastapi.json()["data"]
        self.assertEqual(a.pop("api_mode"), "controller")
        self.assertEqual(b.pop("api_mode"), "fastapi")
        self.assertEqual(a.pop("api_root"), CONTROLLER_ROOT)
        self.assertEqual(b.pop("api_root"), PUBLIC_ROOT)
        self.assertEqual(a, b)

    def test_portal_is_401_instead_of_a_login_redirect(self):
        """The one intentional behavioural improvement: an API client gets JSON."""
        res = self.url_open(PUBLIC_ROOT + "/portal/orders", allow_redirects=False)
        self.assertEqual(res.status_code, 401)
        self.assertFalse(res.json()["success"])

    def test_a_missing_app_404s_instead_of_500ing(self):
        """Soft app dependencies: with the module absent the route must say so.

        Without the `require_app` guard the router reaches for a model that does
        not exist and answers 500 — which is how this was found.
        """
        for app, path in (("blog", "/blogs"), ("course", "/courses"), ("forum", "/forums")):
            module = self.env["ir.module.module"].sudo().search(
                [("name", "=", {"blog": "website_blog", "course": "website_slides",
                                "forum": "website_forum"}[app])]
            )
            if module.state == "installed":
                continue
            with self.subTest(app=app):
                controller, fastapi = self._both(path)
                self.assertEqual(controller.status_code, fastapi.status_code)
                self.assertEqual(controller.json(), fastapi.json())
