"""Plan 16B Tasks 2 and 3 — the portal layer adds entitlement and NOTHING else.

`models/orders/dms_order_api.py` already refuses a client price, refuses a
client company, refuses a SKU outside the assortment, refuses an order over
the credit limit, requires confirmation when the price moved, and collapses a
replayed `operation_uuid` into one order. Section 5 of plan 16 asks for all
six. Rebuilding any of them here would create a second answer to the same
question, and the second answer is the one that goes stale.

So these tests assert two things: that the invariants survive the wrapper,
and that the wrapper adds the one check `dms.order.api` cannot make.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .test_portal_catalog import PortalCatalogCase


@tagged('post_install', '-at_install')
class TestPortalOrderApi(PortalCatalogCase):

    def _api(self):
        return self.env['dms.portal.api'].with_user(self.buyer)

    # --- what the wrapper adds -------------------------------------------

    def test_quote_for_an_outlet_without_entitlement_is_refused(self):
        self._entitle()
        with self.assertRaises(AccessError):
            self._api().dms_portal_quote(
                self.outlet_b.id, [{'product_id': self.product_a.id,
                                    'quantity': 1}])

    def test_submit_for_an_outlet_without_entitlement_creates_nothing(self):
        self._entitle()
        before = self.env['sale.order'].search_count([])
        with self.assertRaises(AccessError):
            self._api().dms_portal_submit(
                self.outlet_b.id, [{'product_id': self.product_a.id,
                                    'quantity': 1}])
        self.assertEqual(self.env['sale.order'].search_count([]), before)

    def test_a_revoked_entitlement_stops_quoting_immediately(self):
        ent = self._entitle()
        ent.with_user(self.approver).action_revoke(reason='contract ended')
        with self.assertRaises(AccessError):
            self._api().dms_portal_quote(
                self.outlet_a.id, [{'product_id': self.product_a.id,
                                    'quantity': 1}])

    # --- what the wrapper must NOT change --------------------------------

    def test_quote_delegates_and_does_not_recompute(self):
        """Two numbers that can disagree are two pricing engines. Section 5
        allows one."""
        self._entitle()
        lines = [{'product_id': self.product_a.id, 'quantity': 3}]
        through_portal = self._api().dms_portal_quote(self.outlet_a.id, lines)
        direct = self.outlet_a.sudo().dms_quote(lines)
        self.assertEqual(through_portal['lines'], direct['lines'])

    def test_a_client_supplied_price_is_still_ignored_through_this_layer(self):
        """`dms` proves this for its own entry point. A wrapper that forwards
        one key too many reopens a door that is shut one file away."""
        self._entitle()
        quote = self._api().dms_portal_quote(
            self.outlet_a.id, [{'product_id': self.product_a.id,
                                'quantity': 1, 'price_unit': 1.0,
                                'discount': 99.0}])
        direct = self.outlet_a.sudo().dms_quote(
            [{'product_id': self.product_a.id, 'quantity': 1}])
        self.assertEqual(quote['lines'], direct['lines'])

    def test_submit_takes_no_client_supplied_company(self):
        """`_SUBMIT_FIELDS` in `dms.order.api` is an allow-list; the wrapper
        must not widen it."""
        self._entitle()
        result = self._api().dms_portal_submit(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'quantity': 1}],
            vals={'company_id': self.env.company.id, 'note': 'from portal'})
        # Assert the order exists before asserting anything about it. Guarding
        # the assertions behind `if result['order_id']` makes the test pass
        # when submit refuses -- which is the failure this test is for.
        self.assertTrue(result['order_id'], result.get('errors'))
        order = self.env['sale.order'].sudo().browse(result['order_id'])
        # `sale.order.note` is Html, so it comes back as Markup('<p>...</p>').
        self.assertIn('from portal', str(order.note))
        self.assertEqual(
            order.company_id, self.dist,
            'company must be the serving Distributor the server resolved, '
            'not anything the client sent')

    def test_submit_carries_dms_flow_type_dsr(self):
        """The most expensive test in 16B.

        Debt 1 of sub-plan 08: `dms.eb2b.order` builds a `sale.order` by its
        own route, sets no `dms_flow_type`, never calls `dms_submit` -- so
        that path has no credit check and no assortment check. This is the
        proof the second channel did not repeat it."""
        self._entitle()
        result = self._api().dms_portal_submit(
            self.outlet_a.id,
            [{'product_id': self.product_a.id, 'quantity': 2}])
        self.assertTrue(result['order_id'], result.get('errors'))
        order = self.env['sale.order'].sudo().browse(result['order_id'])
        self.assertEqual(order.dms_flow_type, 'dsr')
        self.assertEqual(order.dms_team_id, self.team)
        self.assertEqual(order.dms_distributor_company_id, self.dist)

    def test_replay_of_the_same_operation_uuid_returns_the_same_order(self):
        """Section 11: "Same external/source order retry creates one SO."
        The mechanism is `dms.sync.operation._dms_once` from plan 05; this
        proves it survives the portal layer."""
        self._entitle()
        lines = [{'product_id': self.product_a.id, 'quantity': 1}]
        first = self._api().dms_portal_submit(
            self.outlet_a.id, lines, operation_uuid='0199e0f0-0000-7000-8000-000000000001')
        second = self._api().dms_portal_submit(
            self.outlet_a.id, lines, operation_uuid='0199e0f0-0000-7000-8000-000000000001')
        self.assertTrue(first['order_id'], first.get('errors'))
        self.assertEqual(first['order_id'], second['order_id'])
        self.assertTrue(second['replayed'])
