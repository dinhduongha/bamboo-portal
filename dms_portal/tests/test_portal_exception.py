"""Plan 16B Task 4 — a refusal nobody sees is a lost order.

Section 5: "Mismatch price/SKU/Distributor/credit vao exception, khong
auto-create bad SO." `dms.order.api` already does the second half -- it
returns `errors` and builds nothing. The first half is missing: the refusal
reaches the buyer's screen and then evaporates, so nobody at the Distributor
ever learns that a shop tried to order and was turned away.

Section 8 keeps the queue on the inside: "No internal notes, margins, other
Outlet data, raw integration errors or secrets" may reach the portal.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import tagged

from .test_portal_catalog import PortalCatalogCase


@tagged('post_install', '-at_install')
class TestPortalException(PortalCatalogCase):

    def _api(self):
        return self.env['dms.portal.api'].with_user(self.buyer)

    def _no_credit(self):
        self.env['dms.outlet.credit'].sudo().search([
            ('res_partner_id', '=', self.outlet_a.id)]).write(
                {'credit_limit': 0.0})
        self.outlet_a.invalidate_recordset()

    def test_a_credit_block_lands_in_the_queue(self):
        self._entitle()
        self._no_credit()
        result = self._api().dms_portal_submit(
            self.outlet_a.id, [{'product_id': self.product_a.id,
                                'quantity': 1}])
        self.assertFalse(result['order_id'])
        exc = self.env['dms.portal.exception'].sudo().search([
            ('outlet_id', '=', self.outlet_a.id)])
        self.assertEqual(exc.kind, 'credit')
        self.assertEqual(exc.state, 'open')
        self.assertEqual(exc.user_id, self.buyer)

    def test_the_queue_entry_carries_the_number_not_just_a_word(self):
        """"credit failed" tells an operator nothing they can act on. The
        limit and what was left of it are what turns a queue row into a phone
        call."""
        self._entitle()
        self._no_credit()
        self._api().dms_portal_submit(
            self.outlet_a.id, [{'product_id': self.product_a.id,
                                'quantity': 1}])
        exc = self.env['dms.portal.exception'].sudo().search([
            ('outlet_id', '=', self.outlet_a.id)])
        self.assertIn('0', exc.detail)

    def test_a_sku_outside_the_assortment_lands_in_the_queue(self):
        self._entitle()
        result = self._api().dms_portal_submit(
            self.outlet_a.id, [{'product_id': self.product_b.id,
                                'quantity': 1}])
        self.assertFalse(result['order_id'])
        exc = self.env['dms.portal.exception'].sudo().search([
            ('outlet_id', '=', self.outlet_a.id)])
        self.assertEqual(exc.kind, 'assortment')

    def test_a_successful_order_leaves_no_exception(self):
        self._entitle()
        result = self._api().dms_portal_submit(
            self.outlet_a.id, [{'product_id': self.product_a.id,
                                'quantity': 1}])
        self.assertTrue(result['order_id'], result.get('errors'))
        self.assertFalse(self.env['dms.portal.exception'].sudo().search([
            ('outlet_id', '=', self.outlet_a.id)]))

    def test_portal_user_cannot_read_the_queue(self):
        self._entitle()
        self._no_credit()
        self._api().dms_portal_submit(
            self.outlet_a.id, [{'product_id': self.product_a.id,
                                'quantity': 1}])
        with self.assertRaises(AccessError):
            self.env['dms.portal.exception'].with_user(self.buyer).search([])

    def test_the_model_has_a_company_scoped_record_rule(self):
        """An ACL row without a rule is unrestricted for that group: every
        Sales Admin would read every refused portal order in every region.
        `dms`'s own `TestRuleMatrixInvariants` enforces this across the whole
        rule set; this states it locally so the reason travels with the file
        that caused it."""
        rules = self.env['ir.rule'].search([
            ('model_id.model', '=', 'dms.portal.exception')])
        self.assertTrue(rules, 'no record rule on dms.portal.exception')
        for rule in rules:
            self.assertIn('company_id', rule.domain_force or '')

    def test_the_refusal_still_reaches_the_buyer(self):
        """Logging it must not swallow it. A queue that eats the error leaves
        the buyer staring at a form that did nothing."""
        self._entitle()
        self._no_credit()
        result = self._api().dms_portal_submit(
            self.outlet_a.id, [{'product_id': self.product_a.id,
                                'quantity': 1}])
        self.assertTrue(result['errors'])
        self.assertEqual(result['errors'][0]['code'], 'credit_blocked')
