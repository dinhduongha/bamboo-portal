"""Plan 16C Task 6 — the security properties of the portal layer itself.

Section 8: CSRF, session, rate limiting, audit; no internal notes, margins,
other Outlet data, raw integration errors or secrets. Section 11: revoking an
entitlement blocks an active session and any data pull.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .test_portal_catalog import PortalCatalogCase


@tagged('post_install', '-at_install')
class TestPortalSecuritySurface(PortalCatalogCase):

    def _api(self):
        return self.env['dms.portal.api'].with_user(self.buyer)

    def test_every_public_portal_method_derives_its_scope(self):
        """No public method on `dms.portal.api` may take a company, a
        pricelist, a warehouse or a price. A signature with nowhere to put
        one is the only version of this rule that survives later edits --
        an allow-list alone gets widened by somebody who does not know why
        it is narrow (07C settled this for claims).
        """
        import inspect
        forbidden = {'company_id', 'company_ids', 'allowed_company_ids',
                     'pricelist_id', 'warehouse_id', 'price_unit', 'amount',
                     'eligible_amount', 'approved_amount'}
        Model = type(self.env['dms.portal.api'])
        offenders = []
        for name in dir(Model):
            if not name.startswith('dms_portal_'):
                continue
            method = getattr(Model, name, None)
            if not callable(method):
                continue
            params = set(inspect.signature(method).parameters)
            leaked = params & forbidden
            if leaked:
                offenders.append((name, sorted(leaked)))
        self.assertFalse(offenders, f'client-supplied scope accepted: {offenders}')

    def test_a_revoked_entitlement_stops_every_public_method(self):
        """Section 11: revoke blocks an active session AND any data pull.
        Checking one method would leave the next one added unguarded, so this
        walks all of them."""
        ent = self._entitle()
        api = self._api()
        calls = [
            lambda: api.dms_portal_catalog(self.outlet_a.id),
            lambda: api.dms_portal_quote(
                self.outlet_a.id,
                [{'product_id': self.product_a.id, 'quantity': 1}]),
            lambda: api.dms_portal_submit(
                self.outlet_a.id,
                [{'product_id': self.product_a.id, 'quantity': 1}]),
            lambda: api.dms_portal_documents('order', self.outlet_a.id),
            lambda: api.dms_portal_debt(self.outlet_a.id),
            lambda: api.dms_portal_request_return(
                self.outlet_a.id,
                [{'product_id': self.product_a.id, 'qty': 1,
                  'sale_line_id': 1}]),
        ]
        ent.with_user(self.approver).action_revoke(reason='revoked for test')
        for index, call in enumerate(calls):
            with self.subTest(call=index):
                with self.assertRaises(AccessError):
                    call()

    def test_no_public_method_leaks_a_secret_field(self):
        """Section 8 forbids secrets in form, export, API, chatter or log.
        `password=True` never blocked `read()` and does not exist in Odoo 19
        (CLAUDE.md section 5.5), so the guard has to be on what the method
        returns."""
        self._entitle()
        self._listing()
        rows = self._api().dms_portal_catalog(self.outlet_a.id)
        joined = str(rows)
        for needle in ('secret', 'token', 'password', 'api_key'):
            self.assertNotIn(needle, joined.lower())

    def test_an_internal_user_is_not_given_portal_scope(self):
        """Section 7: internal users belong in the back office. Handing them
        the portal domain would narrow them to entitlements they never have,
        hiding their own region from them."""
        domain = self.env['dms.portal.scoped'].with_user(
            self.staff).dms_portal_domain()
        self.assertEqual(domain, [])
